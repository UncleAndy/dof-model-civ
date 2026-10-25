/***********************************************************************
 DOF-Core policy layer for the built-in freeciv AI (contact with strangers).

 Stage M0: knowledge ledger + journal + per-seat policy switch.
 Decision behaviour is NOT changed in this stage.

 Policy switch is a file, read (and re-read on change) by the running server:
     /docker/freeciv/dof_policy.conf     (env DOF_POLICY_FILE overrides)
 Content, one line:
     none | all | even | odd | 0,2,4        ('#' starts a comment)
 "even"/"odd" select AI seats by player index parity - that is how the two
 arms are mixed inside ONE game (control seats stay classic).

 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 2, or (at your option)
 any later version.
***********************************************************************/

#ifdef HAVE_CONFIG_H
#include <fc_config.h>
#endif

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

/* utility */
#include "log.h"
#include "support.h"

/* common */
#include "actions.h"
#include "ai.h"
#include "game.h"
#include "player.h"

#include "dofpolicy.h"

#define DOF_DEFAULT_FILE "/docker/freeciv/dof_policy.conf"
#define DOF_SPEC_LEN 128

enum dof_mode {
  DOF_MODE_NONE = 0,
  DOF_MODE_ALL,
  DOF_MODE_EVEN,
  DOF_MODE_ODD,
  DOF_MODE_LIST
};

/* Per-seat console override: 0 = none, 1 = forced on, 2 = forced off. */
#define DOF_FORCE_NONE 0
#define DOF_FORCE_ON   1
#define DOF_FORCE_OFF  2

static struct {
  bool loaded;
  time_t mtime;
  enum dof_mode mode;
  bool listed[MAX_NUM_PLAYERS];
  char spec[DOF_SPEC_LEN];
  signed char force[MAX_NUM_PLAYERS];
} dof_policy = { FALSE, 0, DOF_MODE_NONE, { FALSE }, "none", { DOF_FORCE_NONE } };

/* Turns on which a pair's war desire was zeroed by the policy. */
static unsigned short dof_suppressed[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];

/* Collapse-source ledger: source_until[attacker][victim] = turn of expiry. */
static int dof_source_until[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];
static bool dof_ledger_reset = FALSE;

/**********************************************************************//**
  A policy file that appeared later than the last read is re-parsed.
**************************************************************************/
static time_t dof_policy_mtime(void)
{
  const char *path = getenv("DOF_POLICY_FILE");
  struct stat st;

  if (path == NULL || path[0] == '\0') {
    path = DOF_DEFAULT_FILE;
  }

  if (stat(path, &st) != 0) {
    return 0;
  }

  return st.st_mtime;
}

/**********************************************************************//**
  Parse one policy spec into the mask.
**************************************************************************/
static void dof_policy_parse(const char *raw)
{
  char buf[DOF_SPEC_LEN];
  const char *p;
  int i;

  for (i = 0; i < MAX_NUM_PLAYERS; i++) {
    dof_policy.listed[i] = FALSE;
  }

  fc_strlcpy(buf, raw, sizeof(buf));

  p = buf;
  while (*p != '\0' && *p != '#') {
    p++;
  }
  while (p > buf && (p[-1] == ' ' || p[-1] == '\t' || p[-1] == '\r'
                     || p[-1] == '\n')) {
    p--;
  }
  buf[p - buf] = '\0';

  if (buf[0] == '\0') {
    fc_strlcpy(dof_policy.spec, "none", sizeof(dof_policy.spec));
    dof_policy.mode = DOF_MODE_NONE;
    return;
  }

  fc_strlcpy(dof_policy.spec, buf, sizeof(dof_policy.spec));

  if (fc_strcasecmp(buf, "none") == 0) {
    dof_policy.mode = DOF_MODE_NONE;
  } else if (fc_strcasecmp(buf, "all") == 0) {
    dof_policy.mode = DOF_MODE_ALL;
  } else if (fc_strcasecmp(buf, "even") == 0) {
    dof_policy.mode = DOF_MODE_EVEN;
  } else if (fc_strcasecmp(buf, "odd") == 0) {
    dof_policy.mode = DOF_MODE_ODD;
  } else {
    dof_policy.mode = DOF_MODE_LIST;

    /* Manual tokenizer: the list is a few numbers, no locale needed. */
    p = buf;
    while (*p != '\0') {
      int idx = 0;
      bool digits = FALSE;

      while (*p == ' ' || *p == ',' || *p == '\t') {
        p++;
      }
      while (*p >= '0' && *p <= '9') {
        idx = idx * 10 + (*p - '0');
        digits = TRUE;
        p++;
      }
      if (digits && idx >= 0 && idx < MAX_NUM_PLAYERS) {
        dof_policy.listed[idx] = TRUE;
      }
      while (*p != '\0' && *p != ',' && *p != ' ' && *p != '\t') {
        p++; /* skip junk between numbers */
      }
    }
  }
}

/**********************************************************************//**
  Unknown is not hostile: DS_NO_CONTACT means the sides never met.
**************************************************************************/
static bool dof_never_met(const struct player *plr1,
                          const struct player *plr2)
{
  return player_diplstate_get(plr1, plr2)->type == DS_NO_CONTACT;
}

/**********************************************************************//**
  Journal helper: every DOF line is machine-parseable ("[DOF] k=v ...").
**************************************************************************/
static void dof_log(const char *fmt, ...)
{
  va_list args;
  char buf[512];

  va_start(args, fmt);
  fc_vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);

  log_normal("[DOF] %s", buf);
}

/**********************************************************************//**
  Reload the policy when the file changed; reset the ledger once per game.
**************************************************************************/
void dof_policy_reload(void)
{
  static int dof_checked_turn = -1;
  time_t mtime;

  if (!dof_ledger_reset) {
    memset(dof_source_until, 0, sizeof(dof_source_until));
    dof_ledger_reset = TRUE;
  }

  /* dof_enabled() is called from tight military loops (POTENTIALLY_HOSTILE_
   * PLAYER), so the policy file is stat()ed at most once per turn. */
  if (dof_policy.loaded && dof_checked_turn == game.info.turn) {
    return;
  }
  dof_checked_turn = game.info.turn;

  mtime = dof_policy_mtime();

  if (dof_policy.loaded && mtime == dof_policy.mtime) {
    return;
  }

  if (mtime == 0) {
    fc_strlcpy(dof_policy.spec, "none", sizeof(dof_policy.spec));
    dof_policy.mode = DOF_MODE_NONE;
  } else {
    FILE *f = fopen(getenv("DOF_POLICY_FILE") != NULL ? getenv("DOF_POLICY_FILE")
                                                      : DOF_DEFAULT_FILE, "r");
    char line[DOF_SPEC_LEN];

    if (f == NULL) {
      fc_strlcpy(dof_policy.spec, "none", sizeof(dof_policy.spec));
      dof_policy.mode = DOF_MODE_NONE;
    } else {
      line[0] = '\0';
      if (fgets(line, sizeof(line), f) == NULL) {
        fc_strlcpy(line, "none", sizeof(line));
      }
      fclose(f);
      dof_policy_parse(line);
    }
  }

  dof_policy.mtime = mtime;
  dof_policy.loaded = TRUE;

  dof_log("policy=%s turn=%d", dof_policy.spec, game.info.turn);

  /* Roster: which AI seats exist and which of them carry the DOF policy.
   * Without it a journal line cannot be attributed to an arm. */
  {
    char roster[1024];
    size_t off = 0;

    roster[0] = '\0';
    players_iterate(plr) {
      if (!is_ai(plr)) {
        continue;
      }
      off += fc_snprintf(roster + off, sizeof(roster) - off, "%s%s:idx=%d:dof=%d",
                         off > 0 ? "," : "", player_name(plr),
                         player_index(plr), dof_enabled(plr) ? 1 : 0);
      if (off >= sizeof(roster) - 96) {
        break;
      }
    } players_iterate_end;
    dof_log("roster ai_seats=[%s]", roster);
  }
}

/**********************************************************************//**
  Is the DOF policy active for this seat?
**************************************************************************/
bool dof_enabled(const struct player *pplayer)
{
  int idx;

  if (pplayer == NULL) {
    return FALSE;
  }

  dof_policy_reload();

  idx = player_index(pplayer);

  if (idx < 0 || idx >= MAX_NUM_PLAYERS) {
    return FALSE;
  }

  if (dof_policy.force[idx] == DOF_FORCE_ON) {
    return TRUE;
  }
  if (dof_policy.force[idx] == DOF_FORCE_OFF) {
    return FALSE;
  }

  switch (dof_policy.mode) {
  case DOF_MODE_ALL:
    return TRUE;
  case DOF_MODE_EVEN:
    return (idx % 2) == 0;
  case DOF_MODE_ODD:
    return (idx % 2) == 1;
  case DOF_MODE_LIST:
    return dof_policy.listed[idx];
  case DOF_MODE_NONE:
  default:
    return FALSE;
  }
}

/**********************************************************************//**
  Is "other" a collapse source for "pplayer"?
**************************************************************************/
bool dof_is_source(const struct player *pplayer,
                   const struct player *other)
{
  int me, him;

  if (pplayer == NULL || other == NULL || pplayer == other) {
    return FALSE;
  }

  me = player_index(pplayer);
  him = player_index(other);

  if (me < 0 || him < 0 || me >= MAX_NUM_PLAYERS || him >= MAX_NUM_PLAYERS) {
    return FALSE;
  }

  return dof_source_until[him][me] > game.info.turn;
}

/**********************************************************************//**
  First contact: the stranger is MET, not hostile.
**************************************************************************/
void dof_journal_contact(struct player *pplayer, struct player *other)
{
  if (!dof_enabled(pplayer) || other == NULL) {
    return;
  }

  dof_log("contact turn=%d me=%s other=%s status=%s", game.info.turn,
          player_name(pplayer), player_name(other),
          dof_is_source(pplayer, other) ? "SOURCE" : "MET");
}

/**********************************************************************//**
  The policy stopped a hostile act: journal it, so that a run without wars
  can be told apart from a run where the rule never had to fire.
**************************************************************************/
void dof_journal_blocked(struct player *pplayer, const struct player *other,
                         const char *what)
{
  if (!dof_enabled(pplayer) || other == NULL) {
    return;
  }

  dof_log("blocked turn=%d me=%s other=%s what=%s", game.info.turn,
          player_name(pplayer), player_name(other), what);
}

/**********************************************************************//**
  The doctrine itself acted: war against a source, ceasefire with a former
  source, coercion refused.
**************************************************************************/
void dof_journal_rule(struct player *pplayer, const struct player *other,
                      const char *what)
{
  if (pplayer == NULL || other == NULL) {
    return;
  }

  dof_log("rule turn=%d me=%s other=%s what=%s", game.info.turn,
          player_name(pplayer), player_name(other), what);
}

/**********************************************************************//**
  Count a turn on which the policy removed the desire to fight this player.
**************************************************************************/
void dof_count_suppressed(const struct player *pplayer,
                          const struct player *other)
{
  int me, him;

  if (pplayer == NULL || other == NULL) {
    return;
  }

  me = player_index(pplayer);
  him = player_index(other);

  if (me < 0 || him < 0 || me >= MAX_NUM_PLAYERS || him >= MAX_NUM_PLAYERS) {
    return;
  }

  if (dof_suppressed[me][him] == 0) {
    dof_log("desire_suppressed turn=%d me=%s other=%s n=1", game.info.turn,
            player_name(pplayer), player_name(other));
  }
  if (dof_suppressed[me][him] < 65000) {
    dof_suppressed[me][him]++;
  }
}

/**********************************************************************//**
  A declaration of war: logged for both arms, so the two seats can be
  compared inside one game.
**************************************************************************/
void dof_journal_declare(struct player *pplayer, const struct player *other,
                         int reason)
{
  if (pplayer == NULL || other == NULL) {
    return;
  }

  dof_log("declare turn=%d declarer=%s target=%s declarer_dof=%d reason=%d",
          game.info.turn, player_name(pplayer), player_name(other),
          dof_enabled(pplayer) ? 1 : 0, reason);
}

/**********************************************************************//**
  Was this action result an attack (a collapse act) rather than a nuisance?
**************************************************************************/
static bool dof_result_is_attack(enum action_result result)
{
  switch (result) {
  case ACTRES_ATTACK:
  case ACTRES_BOMBARD:
  case ACTRES_CAPTURE_UNITS:
  case ACTRES_WIPE_UNITS:
  case ACTRES_SPY_ATTACK:
  case ACTRES_SPY_BRIBE_UNIT:
  case ACTRES_CONQUER_CITY:
  case ACTRES_DESTROY_CITY:
  case ACTRES_SPY_INCITE_CITY:
  case ACTRES_SPY_POISON:
  case ACTRES_SPY_SPREAD_PLAGUE:
  case ACTRES_SPY_SABOTAGE_CITY:
  case ACTRES_SPY_TARGETED_SABOTAGE_CITY:
  case ACTRES_SPY_SABOTAGE_CITY_PRODUCTION:
  case ACTRES_SPY_SABOTAGE_UNIT:
  case ACTRES_SPY_NUKE:
  case ACTRES_NUKE:
  case ACTRES_NUKE_UNITS:
  case ACTRES_STRIKE_BUILDING:
  case ACTRES_STRIKE_PRODUCTION:
    return TRUE;
  default:
    return FALSE;
  }
}

/**********************************************************************//**
  Record an incident: mark the attacker as a collapse source for every DOF
  seat that knows both sides, and write one journal line per such seat.
**************************************************************************/
void dof_ledger_note(int type, const struct action *paction,
                     struct player *violator, struct player *victim)
{
  bool is_attack = FALSE;
  const char *actname = "war";
  int vi, wi;

  if (violator == NULL || victim == NULL || violator == victim) {
    return;
  }

  if (type == (int) INCIDENT_ACTION) {
    if (paction == NULL) {
      return;
    }
    is_attack = dof_result_is_attack(paction->result);
    actname = action_rule_name(paction);
  } else if (type == (int) INCIDENT_WAR) {
    is_attack = FALSE; /* a declaration is news, not a collapse act */
    actname = "declare_war";
  } else {
    return;
  }

  vi = player_index(violator);
  wi = player_index(victim);

  if (is_attack && vi >= 0 && vi < MAX_NUM_PLAYERS
      && wi >= 0 && wi < MAX_NUM_PLAYERS) {
    dof_source_until[vi][wi] = game.info.turn + DOF_SOURCE_HORIZON;
  }

  /* Unconditional record: without it a "peaceful" run cannot be told apart
   * from a run where the instrument never saw a war. Every seat is reported,
   * both arms, with its flag. */
  dof_log("%s turn=%d violator=%s victim=%s violator_dof=%d victim_dof=%d",
          is_attack ? "attack" : "news", game.info.turn,
          player_name(violator), player_name(victim),
          dof_enabled(violator) ? 1 : 0, dof_enabled(victim) ? 1 : 0);

  players_iterate(receiver) {
    if (!dof_enabled(receiver) || receiver == violator) {
      continue;
    }
    if (dof_never_met(receiver, violator) || dof_never_met(receiver, victim)) {
      continue;
    }
    dof_log("event turn=%d act=%s violator=%s victim=%s mark=%s me=%s %s",
            game.info.turn, actname, player_name(violator),
            player_name(victim), is_attack ? "SOURCE" : "NEWS",
            player_name(receiver),
            dof_is_source(receiver, violator) ? "status=SOURCE" : "status=MET");
  } players_iterate_end;
}

/**********************************************************************//**
  AI console: "/aicmd <player> dof on|off|status".
**************************************************************************/
void dof_player_console(struct player *pplayer, const char *cmd)
{
  char verb[32];
  int idx = player_index(pplayer);

  if (cmd == NULL) {
    return;
  }

  while (*cmd == ' ') {
    cmd++;
  }
  if (fc_strncasecmp(cmd, "dof", 3) != 0) {
    dof_log("console unknown me=%s cmd=\"%s\"", player_name(pplayer), cmd);
    return;
  }
  cmd += 3;
  while (*cmd == ' ') {
    cmd++;
  }
  fc_strlcpy(verb, cmd, sizeof(verb));
  {
    char *sp = strchr(verb, ' ');

    if (sp != NULL) {
      *sp = '\0';
    }
  }

  if (idx < 0 || idx >= MAX_NUM_PLAYERS) {
    return;
  }

  if (fc_strcasecmp(verb, "on") == 0) {
    dof_policy.force[idx] = DOF_FORCE_ON;
  } else if (fc_strcasecmp(verb, "off") == 0) {
    dof_policy.force[idx] = DOF_FORCE_OFF;
  } else if (fc_strcasecmp(verb, "status") != 0) {
    dof_log("console unknown me=%s arg=\"%s\"", player_name(pplayer), verb);
    return;
  }

  dof_log("console me=%s arg=%s enabled=%s policy=%s", player_name(pplayer),
          verb, dof_enabled(pplayer) ? "yes" : "no", dof_policy_spec());
}

/**********************************************************************//**
  The current policy spec.
**************************************************************************/
const char *dof_policy_spec(void)
{
  return dof_policy.spec;
}
