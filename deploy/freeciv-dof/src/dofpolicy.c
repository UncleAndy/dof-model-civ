/***********************************************************************
 DOF-Core policy layer for the built-in freeciv AI (contact with strangers).

 Principle: DOF-Core, https://github.com/UncleAndy/dof-core
 Description of every engine change: DOF-AGENT.md / drafts/DOF_ENGINE_CHANGES.md

 Stages: M0 knowledge ledger + journal + per-seat policy switch; M1 no war
 without an observed attack; M2 coercion refused; M3 war of response and a
 peace offer when the source flag expires; M4 solidarity (an attack on a
 third party the seat knows both sides of is answered the same way).

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
#include "unit.h"
#include "unittype.h"

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
  unsigned flags;               /* DOF_F_* rule set of a DOF seat */
  signed char force[MAX_NUM_PLAYERS];
} dof_policy = { FALSE, 0, DOF_MODE_NONE, { FALSE }, "none", DOF_F_FULL,
                 { DOF_FORCE_NONE } };

/* Turns on which a pair's war desire was zeroed by the policy. */
static unsigned short dof_suppressed[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];

/* Collapse-source ledger, one entry per attacking UNIT. The source of collapse
 * is the unit that performed the attack, not the nation it belongs to: the
 * response is aimed at those units and ends when they are gone. */
#define DOF_MAX_INCIDENTS 512

struct dof_incident {
  int unit_id;    /* 0 when the incident names no unit (fallback) */
  int owner;      /* player index of the attacker */
  int victim;     /* player index of the victim */
  int turn;       /* turn of the attack */
  bool used;
  bool gone_logged;
  bool on_source; /* M7: the victim was already a collapse source, so this
                   * attack is an answer, not a collapse act. The record is
                   * kept for the journal, but it never classifies its author
                   * as a source and never grounds solidarity. */
};

static struct dof_incident dof_incidents[DOF_MAX_INCIDENTS];
static int dof_incident_next = 0;

/* Who started the current conflict between two players: the side that attacked
 * first. A counter-attack by the victim is defence and never makes a source,
 * otherwise every war would criminalise both sides. */
static int dof_pair_aggressor[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];
static int dof_pair_turn[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];
static bool dof_pair_init = FALSE;
static bool dof_ledger_reset = FALSE;

/* Separate accounting of the marks and rule firings that involve barbarians.
 * Statistics only: no decision reads these counters, the algorithm is the same
 * with and without them. */
static int dof_barb_marks = 0;
static int dof_barb_rules = 0;
/* M7: attacks on an already declared collapse source (kept, never a source). */
static int dof_attacks_on_source = 0;
static int dof_summary_turn = -1;

/* Unit performing an action right now, set by server/unithand.c. */
static int dof_acting_unit_id = 0;

/* ---- Audit counters (P0) -------------------------------------------------
 * blocked actions were counted by journal lines only, and the same rejected
 * request could be asked again and again inside one turn: the published
 * "blocked" number measured attempts, not events. Both are kept now, and a
 * per-turn set of keys keeps the journal to one line per distinct event.
 * Nothing here is read by a decision: instrumentation only. */
#define DOF_BLOCK_SLOTS 16384
#define DOF_BLOCK_PROBE 24
#define DOF_BLOCK_DECLARE 0
#define DOF_BLOCK_ATTACK  1
#define DOF_BLOCK_KINDS   2

struct dof_block_slot {
  int turn;   /* slot is valid for this turn only (0 = free) */
  int me, other, unit, kind;
};

static struct dof_block_slot dof_block_tab[DOF_BLOCK_SLOTS];
static int dof_blk_att[DOF_BLOCK_KINDS];
static int dof_blk_uniq[DOF_BLOCK_KINDS];
static int dof_blk_att_seat[MAX_NUM_PLAYERS];
static int dof_blk_uniq_seat[MAX_NUM_PLAYERS];

/* Suppressed war desire: pairs (logged once) and events (every call). */
static int dof_supp_pairs;
static int dof_supp_pairs_seat[MAX_NUM_PLAYERS];
static int dof_supp_events;
static int dof_supp_events_seat[MAX_NUM_PLAYERS];

/* Per-seat counters that the journal only ever showed as text lines. */
static int dof_declares_seat[MAX_NUM_PLAYERS];
static int dof_on_source_seat[MAX_NUM_PLAYERS];
static int dof_marks_seat[MAX_NUM_PLAYERS];
static int dof_gone_seat[MAX_NUM_PLAYERS];
static int dof_rules_seat[MAX_NUM_PLAYERS];
static bool dof_totals_done = FALSE;

/* Live subset of the ledger for this turn, plus the derived per-seat view
 * known_source[me][attacker]: the attacker still has a living marked unit
 * against somebody "me" knows, so "me" can tell the aggressor from the victim
 * and acts against the aggressor (solidarity). */
static struct dof_incident dof_live[DOF_MAX_INCIDENTS];
static int dof_live_count = -1;
static int dof_live_turn = -1;   /* ход, на который построен срез */
static bool dof_known_source[MAX_NUM_PLAYERS][MAX_NUM_PLAYERS];

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
  Rule set of a preset. "full" is the published behaviour; the rest are
  ablations, each one turning off everything that is not needed to test a
  single rule.
**************************************************************************/
static unsigned dof_preset_flags(const char *name)
{
  if (name == NULL || name[0] == '\0' || fc_strcasecmp(name, "full") == 0) {
    return DOF_F_FULL;
  }
  if (fc_strcasecmp(name, "ban") == 0) {
    /* Только прямой запрет: не начинать войн ни по одному поводу (желание,
     * обида, космос, «некого бить», война за союзника, незнакомец) и не бить
     * не-источника. Ответ на нападение в этот набор не входит. */
    return DOF_F_BAN | DOF_F_ATTACK | DOF_F_UNKNOWN
           | DOF_F_SPACE | DOF_F_NO_TARGET | DOF_F_ALLY_WAR;
  }
  if (fc_strcasecmp(name, "selfdef") == 0) {
    /* Мир в первую очередь, но на нападение на себя — ответ. */
    return dof_preset_flags("ban") | DOF_F_SELFDEF | DOF_F_RAMPAGE;
  }
  if (fc_strcasecmp(name, "solidarity") == 0) {
    return dof_preset_flags("selfdef") | DOF_F_SOLIDARITY;
  }
  if (fc_strcasecmp(name, "nocoerce") == 0) {
    return dof_preset_flags("solidarity") | DOF_F_COERCE;
  }
  if (fc_strcasecmp(name, "nowarblock") == 0) {
    /* Полный DOF без блока войны: место вправе начинать войны по любому
     * поводу, остальные правила (ответ, солидарность, принуждение, мир,
     * приоритет помеченных юнитов) работают. */
    return DOF_F_FULL & ~(DOF_F_BAN | DOF_F_ATTACK | DOF_F_UNKNOWN
                          | DOF_F_SPACE | DOF_F_NO_TARGET | DOF_F_ALLY_WAR);
  }
  return 0; /* unknown preset */
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

  /* Preset after ':': "even:ban" carries the rule set of "ban". A spec without
   * a preset keeps the full rule set, so every old file means what it meant. */
  {
    char *colon = strchr(buf, ':');
    char *preset = NULL;

    if (colon != NULL) {
      *colon = '\0';
      preset = colon + 1;
    }
    if (preset == NULL || preset[0] == '\0') {
      dof_policy.flags = DOF_F_FULL;
    } else {
      dof_policy.flags = dof_preset_flags(preset);
      if (dof_policy.flags == 0) {
        /* Unknown preset: never silently change behaviour — keep the full set
         * and make the mistake visible in the journal. */
        dof_policy.flags = DOF_F_FULL;
        log_error("[DOF] unknown preset \"%s\" in policy \"%s\", using full",
                  preset, dof_policy.spec);
      }
    }
  }

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

  /* Стенд (publite2) держит движки с --log ../logs/..., но в этом окружении
   * файл журнала не обновляется — строки теряются. Дублируем в stderr: он
   * всегда попадает в /docker/logs/freeciv-web-stderr-<port>.log, поэтому
   * поведение DOF на живом стенде видно без правки аргументов запуска. */
  fprintf(stderr, "[DOF] %s\n", buf);
  fflush(stderr);
}

/**********************************************************************//**
  Reload the policy when the file changed; reset the ledger once per game.
**************************************************************************/
void dof_policy_reload(void)
{
  static int dof_checked_turn = -1;
  static int dof_last_turn = -1;
  time_t mtime;

  /* Новая партия в том же процессе (движок живёт с --keep, номер хода
   * пошёл назад): источники прошлой игры не должны переехать в новую. */
  if (game.info.turn < dof_last_turn) {
    memset(dof_incidents, 0, sizeof(dof_incidents));
    memset(dof_live, 0, sizeof(dof_live));
    memset(dof_suppressed, 0, sizeof(dof_suppressed));
    memset(dof_known_source, 0, sizeof(dof_known_source));
    memset(dof_pair_aggressor, 0, sizeof(dof_pair_aggressor));
    memset(dof_pair_turn, 0, sizeof(dof_pair_turn));
    dof_pair_init = FALSE;
    dof_incident_next = 0;
    dof_live_count = -1;
    dof_live_turn = -1;
    dof_acting_unit_id = 0;
    dof_policy.loaded = FALSE;
    dof_checked_turn = -1;
    dof_barb_marks = 0;
    dof_barb_rules = 0;
    dof_summary_turn = -1;
    memset(dof_block_tab, 0, sizeof(dof_block_tab));
    memset(dof_blk_att, 0, sizeof(dof_blk_att));
    memset(dof_blk_uniq, 0, sizeof(dof_blk_uniq));
    memset(dof_blk_att_seat, 0, sizeof(dof_blk_att_seat));
    memset(dof_blk_uniq_seat, 0, sizeof(dof_blk_uniq_seat));
    memset(dof_supp_pairs_seat, 0, sizeof(dof_supp_pairs_seat));
    memset(dof_supp_events_seat, 0, sizeof(dof_supp_events_seat));
    memset(dof_declares_seat, 0, sizeof(dof_declares_seat));
    memset(dof_on_source_seat, 0, sizeof(dof_on_source_seat));
    memset(dof_marks_seat, 0, sizeof(dof_marks_seat));
    memset(dof_gone_seat, 0, sizeof(dof_gone_seat));
    memset(dof_rules_seat, 0, sizeof(dof_rules_seat));
    dof_supp_pairs = 0;
    dof_supp_events = 0;
    dof_totals_done = FALSE;
  }
  dof_last_turn = game.info.turn;

  /* Барварский учёт печатается раз в 50 ходов: без него долю варваров в
   * журнале приходится считать по тексту строк. */
  if (game.info.turn % 50 == 0 && dof_summary_turn != game.info.turn) {
    dof_summary_turn = game.info.turn;
    dof_log("barb_summary turn=%d marks=%d rules=%d on_source=%d",
            game.info.turn, dof_barb_marks, dof_barb_rules,
            dof_attacks_on_source);
  }

  if (!dof_ledger_reset) {
    memset(dof_incidents, 0, sizeof(dof_incidents));
    memset(dof_live, 0, sizeof(dof_live));
    dof_incident_next = 0;
    dof_live_count = -1;
    dof_live_turn = -1;
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

  dof_log("policy=%s turn=%d flags=0x%x", dof_policy.spec, game.info.turn,
          dof_policy.flags);

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
  Which rules this seat carries. 0 for a classic seat: every gate below reads
  its own bit, so an ablation never needs a second switch.
**************************************************************************/
unsigned dof_flags(const struct player *pplayer)
{
  if (!dof_enabled(pplayer)) {
    return 0;
  }

  return dof_policy.flags;
}

bool dof_flag(const struct player *pplayer, unsigned flag)
{
  return (dof_flags(pplayer) & flag) != 0;
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
  Do both seats of a pair carry the policy? Diplomatic state is symmetric and
  pairwise, so an engine rule may only be suspended when both sides are DOF.
**************************************************************************/
bool dof_pair_enabled(const struct player *one, const struct player *two)
{
  return dof_enabled(one) && dof_enabled(two);
}

/**********************************************************************//**
  Is this recorded incident still a live source? The unit must still exist and
  belong to the recorded attacker: the source of collapse is the unit, so the
  response ends when the unit is gone.
**************************************************************************/
static bool dof_incident_live(const struct dof_incident *inc)
{
  struct unit *punit;

  if (!inc->used || inc->owner < 0 || inc->owner >= MAX_NUM_PLAYERS
      || inc->victim < 0 || inc->victim >= MAX_NUM_PLAYERS) {
    return FALSE;
  }

  /* Hard cap, so that a unit hidden forever cannot keep a war alive. */
  if (inc->turn + DOF_SOURCE_HORIZON * 3 <= game.info.turn) {
    return FALSE;
  }

  if (inc->unit_id > 0) {
    punit = game_unit_by_number(inc->unit_id);
    if (punit == NULL || player_index(unit_owner(punit)) != inc->owner) {
      return FALSE;
    }
  } else if (inc->turn + DOF_SOURCE_HORIZON <= game.info.turn) {
    /* Incident that names no unit: the plain time window applies. */
    return FALSE;
  }

  return TRUE;
}

/**********************************************************************//**
  Rebuild the live subset once per turn and derive, for every seat, which
  players still hold a living marked unit against somebody that seat knows.
**************************************************************************/
static void dof_live_refresh(void)
{
  int i;

  /* The snapshot is valid for one turn only: a marked unit can die without
   * producing any new incident, and a source must vanish with its unit. */
  if (dof_live_count >= 0 && dof_live_turn == game.info.turn) {
    return;
  }

  dof_live_turn = game.info.turn;

  dof_live_count = 0;
  memset(dof_known_source, 0, sizeof(dof_known_source));

  for (i = 0; i < DOF_MAX_INCIDENTS; i++) {
    struct dof_incident *inc = &dof_incidents[i];
    struct player *attacker;
    struct player *sufferer;

    if (!inc->used) {
      continue;
    }

    if (inc->on_source) {
      /* M7: an answer to a declared source is never a source itself, so it
       * stays out of the snapshot that grounds both defence and solidarity. */
      continue;
    }

    attacker = player_by_number(inc->owner);
    sufferer = player_by_number(inc->victim);

    if (!dof_incident_live(inc)) {
      if (!inc->gone_logged && inc->unit_id > 0) {
        inc->gone_logged = TRUE;
        if (inc->owner >= 0 && inc->owner < MAX_NUM_PLAYERS) {
          dof_gone_seat[inc->owner]++;
        }
        dof_log("unit_gone turn=%d unit=%d owner=%s victim=%s",
                game.info.turn, inc->unit_id,
                attacker != NULL ? player_name(attacker) : "?",
                sufferer != NULL ? player_name(sufferer) : "?");
      }
      continue;
    }

    dof_live[dof_live_count++] = *inc;

    if (attacker == NULL) {
      continue;
    }

    /* Attacks on barbarians are pest control, not a collapse act: a player
     * that clears a barbarian band must not become a legitimate target for
     * every seat that knows the barbarians. The barbarian ledger still counts
     * these incidents separately. */
    if (sufferer != NULL && is_barbarian(sufferer)) {
      continue;
    }

    players_iterate(receiver) {
      const int rcv = player_index(receiver);

      if (rcv < 0 || rcv >= MAX_NUM_PLAYERS || receiver == attacker) {
        continue;
      }
      if (dof_never_met(receiver, attacker)) {
        continue;
      }
      if (sufferer != NULL && !dof_never_met(receiver, sufferer)) {
        dof_known_source[rcv][inc->owner] = TRUE;
      }
    } players_iterate_end;
  }
}

/**********************************************************************//**
  Is "other" a collapse source for "pplayer"? TRUE while at least one unit of
  "other" that attacked somebody "pplayer" knows is still alive.
**************************************************************************/
bool dof_is_source(const struct player *pplayer,
                   const struct player *other)
{
  int i, me, him;

  if (pplayer == NULL || other == NULL || pplayer == other) {
    return FALSE;
  }

  me = player_index(pplayer);
  him = player_index(other);

  if (me < 0 || him < 0 || me >= MAX_NUM_PLAYERS || him >= MAX_NUM_PLAYERS) {
    return FALSE;
  }

  dof_live_refresh();

  if (!dof_known_source[me][him]) {
    return FALSE;
  }

  /* The snapshot is built once per turn; a marked unit may already be dead.
   * The collapse source is the unit, so verify against the map right now. */
  for (i = 0; i < DOF_MAX_INCIDENTS; i++) {
    const struct dof_incident *inc = &dof_incidents[i];
    const struct player *victim;

    if (!inc->used || inc->owner != him) {
      continue;
    }
    if (!dof_incident_live(inc)) {
      continue;
    }
    victim = player_by_number(inc->victim);
    if (victim != NULL && !dof_never_met(pplayer, victim)) {
      return TRUE;
    }
  }

  return FALSE;
}

/**********************************************************************//**
  Is THIS unit a collapse source for "pplayer"? The unit itself performed an
  attack on somebody "pplayer" knows and is still alive.
**************************************************************************/
bool dof_unit_is_source(const struct player *pplayer,
                        const struct unit *punit)
{
  int i, me;
  const struct player *owner;

  if (pplayer == NULL || punit == NULL) {
    return FALSE;
  }

  owner = unit_owner(punit);
  if (owner == NULL || owner == pplayer) {
    return FALSE;
  }

  me = player_index(pplayer);
  if (me < 0 || me >= MAX_NUM_PLAYERS) {
    return FALSE;
  }
  if (dof_never_met(pplayer, owner)) {
    return FALSE;
  }

  dof_live_refresh();

  for (i = 0; i < dof_live_count; i++) {
    const struct dof_incident *inc = &dof_live[i];
    const struct player *victim;

    if (inc->unit_id != punit->id || inc->owner != player_index(owner)) {
      continue;
    }
    victim = player_by_number(inc->victim);
    if (victim == pplayer
        || (victim != NULL && !dof_never_met(pplayer, victim))) {
      return TRUE;
    }
  }

  return FALSE;
}

/**********************************************************************//**
  How many living marked units of "owner" does "pplayer" know about?
**************************************************************************/
int dof_source_unit_count(const struct player *pplayer,
                          const struct player *owner)
{
  int i, k, me, him;
  int seen[DOF_MAX_INCIDENTS];
  int n = 0;

  if (pplayer == NULL || owner == NULL) {
    return 0;
  }

  me = player_index(pplayer);
  him = player_index(owner);

  if (me < 0 || him < 0 || me >= MAX_NUM_PLAYERS || him >= MAX_NUM_PLAYERS) {
    return 0;
  }
  if (dof_never_met(pplayer, owner)) {
    return 0;
  }

  dof_live_refresh();

  for (i = 0; i < dof_live_count; i++) {
    const struct dof_incident *inc = &dof_live[i];
    const struct player *victim;
    bool dup = FALSE;

    if (inc->owner != him) {
      continue;
    }
    victim = player_by_number(inc->victim);
    if (victim == NULL) {
      continue;
    }
    if (victim != pplayer && dof_never_met(pplayer, victim)) {
      continue;
    }
    for (k = 0; k < n; k++) {
      if (seen[k] == inc->unit_id) {
        dup = TRUE;
        break;
      }
    }
    if (!dup) {
      seen[n++] = inc->unit_id;
    }
  }

  return n;
}

/**********************************************************************//**
  Is "other" a source for "pplayer" only because of attacks on THIRD parties?
**************************************************************************/
bool dof_source_is_third_party(const struct player *pplayer,
                               const struct player *other)
{
  int i, me, him;
  bool by_third = FALSE;

  if (pplayer == NULL || other == NULL || pplayer == other) {
    return FALSE;
  }

  me = player_index(pplayer);
  him = player_index(other);

  if (me < 0 || him < 0 || me >= MAX_NUM_PLAYERS || him >= MAX_NUM_PLAYERS) {
    return FALSE;
  }

  dof_live_refresh();

  for (i = 0; i < dof_live_count; i++) {
    const struct dof_incident *inc = &dof_live[i];
    const struct player *victim;

    if (inc->owner != him) {
      continue;
    }
    if (inc->victim == me) {
      return FALSE; /* attacked us: self-defence, not solidarity */
    }
    victim = player_by_number(inc->victim);
    if (victim != NULL && !dof_never_met(pplayer, victim)) {
      by_third = TRUE;
    }
  }

  return by_third;
}

/**********************************************************************//**
  Is "owner" the side that started this conflict with "victim"? Only the side
  that attacked first is a collapse source: a counter-attack is defence, and
  telling the aggressor from the defender is exactly what the agent must do.
**************************************************************************/
static bool dof_pair_is_initiator(int owner, int victim)
{
  if (!dof_pair_init) {
    int i, k;

    for (i = 0; i < MAX_NUM_PLAYERS; i++) {
      for (k = 0; k < MAX_NUM_PLAYERS; k++) {
        dof_pair_aggressor[i][k] = -1;
      }
    }
    dof_pair_init = TRUE;
  }

  /* An old conflict is forgotten: a fresh attack starts a fresh one. */
  if (dof_pair_turn[owner][victim] + DOF_SOURCE_HORIZON * 3
      <= game.info.turn) {
    dof_pair_aggressor[owner][victim] = -1;
  }
  if (dof_pair_turn[victim][owner] + DOF_SOURCE_HORIZON * 3
      <= game.info.turn) {
    dof_pair_aggressor[victim][owner] = -1;
  }

  if (dof_pair_aggressor[victim][owner] == victim) {
    /* The other side attacked first: this is a counter-attack. */
    dof_pair_turn[owner][victim] = game.info.turn;
    return FALSE;
  }

  dof_pair_aggressor[owner][victim] = owner;
  dof_pair_turn[owner][victim] = game.info.turn;

  return TRUE;
}

/**********************************************************************//**
  Is this player a declared collapse source right now - for anyone? The
  ledger holds one record per attacking unit; the M7 flag marks answers to a
  source and such records do not count here, so answering a source never
  chains a new one.
**************************************************************************/
static bool dof_is_source_any(int victim)
{
  int i;

  dof_live_refresh();

  for (i = 0; i < dof_live_count; i++) {
    if (dof_live[i].owner == victim) {
      return TRUE;
    }
  }

  return FALSE;
}

/**********************************************************************//**
  Record one attacking unit in the ledger and journal it. An attack performed
  by the same unit on the same victim in the same turn is recorded once.
**************************************************************************/
static void dof_incident_add(int unit_id, int owner, int victim)
{
  struct dof_incident *inc = &dof_incidents[dof_incident_next];
  struct player *attacker = player_by_number(owner);
  struct player *sufferer = player_by_number(victim);
  struct unit *punit = unit_id > 0 ? game_unit_by_number(unit_id) : NULL;
  bool on_source;
  int i;

  for (i = 0; i < DOF_MAX_INCIDENTS; i++) {
    const struct dof_incident *old = &dof_incidents[i];

    if (old->used && old->unit_id == unit_id && old->owner == owner
        && old->victim == victim && old->turn == game.info.turn) {
      return; /* already known: one entry per unit, victim and turn */
    }
  }

  /* DOF (M7): an attack on a player who is already a declared collapse source
   * is an answer, not a collapse act. It is recorded with the flag so that the
   * journal and the statistics keep it, but it never classifies the attacker. */
  on_source = dof_is_source_any(victim);

  if (!on_source && !dof_pair_is_initiator(owner, victim)) {
    /* A counter-attack by the defending side: not a source of collapse. */
    return;
  }

  inc->unit_id = unit_id;
  inc->owner = owner;
  inc->victim = victim;
  inc->turn = game.info.turn;
  inc->used = TRUE;
  inc->gone_logged = FALSE;
  inc->on_source = on_source;

  dof_incident_next = (dof_incident_next + 1) % DOF_MAX_INCIDENTS;
  dof_live_count = -1;

  /* Варвары учитываются отдельной меткой: и как нападавший, и как жертва.
   * На решения это не влияет — только на разбор журнала. */
  if ((attacker != NULL && is_barbarian(attacker))
      || (sufferer != NULL && is_barbarian(sufferer))) {
    dof_barb_marks++;
    dof_log("unit_source_barb turn=%d unit=%d utype=%s owner=%s victim=%s",
            game.info.turn, unit_id,
            punit != NULL ? unit_rule_name(punit) : "?",
            attacker != NULL ? player_name(attacker) : "?",
            sufferer != NULL ? player_name(sufferer) : "?");
    return;
  }

  if (on_source) {
    /* M7: kept for the journal, but this record is not a collapse source. */
    dof_attacks_on_source++;
    if (owner >= 0 && owner < MAX_NUM_PLAYERS) {
      dof_on_source_seat[owner]++;
    }
    dof_log("unit_source_on_source turn=%d unit=%d utype=%s owner=%s victim=%s",
            game.info.turn, unit_id,
            punit != NULL ? unit_rule_name(punit) : "?",
            attacker != NULL ? player_name(attacker) : "?",
            sufferer != NULL ? player_name(sufferer) : "?");
    return;
  }

  if (owner >= 0 && owner < MAX_NUM_PLAYERS) {
    dof_marks_seat[owner]++;
  }

  dof_log("unit_source turn=%d unit=%d utype=%s owner=%s victim=%s",
          game.info.turn, unit_id,
          punit != NULL ? unit_rule_name(punit) : "?",
          attacker != NULL ? player_name(attacker) : "?",
          sufferer != NULL ? player_name(sufferer) : "?");
}

/**********************************************************************//**
  Remember which unit is performing an action (called from server/unithand.c).
**************************************************************************/
void dof_set_acting_unit(const struct unit *punit)
{
  dof_acting_unit_id = punit != NULL ? punit->id : 0;
}

/**********************************************************************//**
  An attack performed by a unit on a player: record the unit itself. Called
  directly from server/unithand.c, because a war-time attack carries no casus
  belli and therefore never reaches call_incident().
**************************************************************************/
void dof_note_unit_attack(const struct unit *punit, struct player *victim)
{
  const struct player *owner;
  int vi, wi;

  if (punit == NULL || victim == NULL) {
    return;
  }

  owner = unit_owner(punit);
  if (owner == NULL || owner == victim) {
    return;
  }

  vi = player_index(owner);
  wi = player_index(victim);

  if (vi < 0 || wi < 0 || vi >= MAX_NUM_PLAYERS || wi >= MAX_NUM_PLAYERS) {
    return;
  }

  dof_incident_add(punit->id, vi, wi);
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
  Has this rejection already happened in this turn? Open addressing with the
  turn as the validity marker: keys of earlier turns are free without a clear.

  Returns TRUE when the event was already seen (so the journal stays at one
  line per distinct event), FALSE on the first sighting.
**************************************************************************/
static bool dof_block_seen(int me, int other, int unit, int kind, int turn)
{
  unsigned h = (unsigned) me * 73856093u ^ (unsigned) other * 19349663u
               ^ (unsigned) unit * 83492791u ^ (unsigned) kind * 2654435761u;
  unsigned base = h & (DOF_BLOCK_SLOTS - 1);
  int probe;

  for (probe = 0; probe < DOF_BLOCK_PROBE; probe++) {
    struct dof_block_slot *slot
      = &dof_block_tab[(base + probe) & (DOF_BLOCK_SLOTS - 1)];

    if (slot->turn != turn) {
      slot->turn = turn;
      slot->me = me;
      slot->other = other;
      slot->unit = unit;
      slot->kind = kind;
      return FALSE;
    }
    if (slot->me == me && slot->other == other
        && slot->unit == unit && slot->kind == kind) {
      return TRUE;
    }
  }

  /* Table pressure: report as unique. An attempt is never lost, only a
   * duplicate line is kept. */
  return FALSE;
}

/**********************************************************************//**
  The policy stopped a hostile act: journal it, so that a run without wars
  can be told apart from a run where the rule never had to fire.

  An AI asks for the same forbidden action many times per turn (every unit
  re-considers, every target re-evaluates), so the journal line is written
  once per distinct (seat, target, unit, turn); the counters keep every
  attempt. Both numbers are reported in the end-of-game totals.
**************************************************************************/
void dof_journal_blocked(struct player *pplayer, const struct player *other,
                         const char *what)
{
  int me, kind, unit;

  if (!dof_enabled(pplayer) || other == NULL) {
    return;
  }

  me = player_index(pplayer);
  kind = (strcmp(what, "declare_war") == 0) ? DOF_BLOCK_DECLARE
                                            : DOF_BLOCK_ATTACK;
  unit = (kind == DOF_BLOCK_ATTACK) ? dof_acting_unit_id : 0;

  dof_blk_att[kind]++;
  if (me >= 0 && me < MAX_NUM_PLAYERS) {
    dof_blk_att_seat[me]++;
  }

  if (dof_block_seen(me, player_index(other), unit, kind, game.info.turn)) {
    return;
  }

  dof_blk_uniq[kind]++;
  if (me >= 0 && me < MAX_NUM_PLAYERS) {
    dof_blk_uniq_seat[me]++;
  }

  dof_log("blocked turn=%d me=%s other=%s what=%s unit=%d%s",
          game.info.turn, player_name(pplayer), player_name(other), what,
          unit, is_barbarian(other) ? " barb=1" : "");
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

  if (player_index(pplayer) >= 0 && player_index(pplayer) < MAX_NUM_PLAYERS) {
    dof_rules_seat[player_index(pplayer)]++;
  }

  /* Варварские пары считаются отдельно; формат строки для остальных не
   * меняется, поле barb=1 добавляется только там, где варвар участвует. */
  if (is_barbarian(pplayer) || is_barbarian(other)) {
    dof_barb_rules++;
    dof_log("rule turn=%d me=%s other=%s what=%s barb=1", game.info.turn,
            player_name(pplayer), player_name(other), what);
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

  dof_supp_events++;
  dof_supp_events_seat[me]++;

  if (dof_suppressed[me][him] == 0) {
    dof_supp_pairs++;
    dof_supp_pairs_seat[me]++;
    dof_log("desire_suppressed turn=%d me=%s other=%s n=1",
            game.info.turn, player_name(pplayer), player_name(other));
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

  if (player_index(pplayer) >= 0 && player_index(pplayer) < MAX_NUM_PLAYERS) {
    dof_declares_seat[player_index(pplayer)]++;
  }
  dof_log("declare turn=%d declarer=%s target=%s declarer_dof=%d reason=%d%s",
          game.info.turn, player_name(pplayer), player_name(other),
          dof_enabled(pplayer) ? 1 : 0, reason,
          is_barbarian(other) ? " barb=1" : "");
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
    /* The source is the unit that performed the act, when we know it, and the
     * player as a fallback otherwise. */
    if (dof_acting_unit_id > 0) {
      struct unit *punit = game_unit_by_number(dof_acting_unit_id);

      if (punit != NULL && player_index(unit_owner(punit)) == vi) {
        dof_incident_add(dof_acting_unit_id, vi, wi);
      } else {
        dof_incident_add(0, vi, wi);
      }
    } else {
      dof_incident_add(0, vi, wi);
    }
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

  dof_log("console me=%s arg=%s enabled=%s policy=%s barb_marks=%d barb_rules=%d",
          player_name(pplayer), verb, dof_enabled(pplayer) ? "yes" : "no",
          dof_policy_spec(), dof_barb_marks, dof_barb_rules);
}

/**********************************************************************//**
  End-of-game totals: one line per seat, all counters in one place.

  The journal is a stream of events and a reader has to sample it (the first
  40 declarations, the first 40 attacks); these totals are complete and are
  what a report should cite for counters. Called once from server/srv_main.c
  in srv_scores(), where every player's score has been recalculated.
**************************************************************************/
void dof_totals_report(void)
{
  if (dof_totals_done) {
    return;
  }
  dof_totals_done = TRUE;

  players_iterate(plr) {
    int me = player_index(plr);
    int live = 0;
    int i;

    if (me < 0 || me >= MAX_NUM_PLAYERS) {
      continue;
    }

    for (i = 0; i < DOF_MAX_INCIDENTS; i++) {
      const struct dof_incident *inc = &dof_incidents[i];

      if (inc->used && !inc->on_source && inc->owner == me
          && dof_incident_live(inc)) {
        live++;
      }
    }

    dof_log("totals turn=%d me=%s idx=%d dof=%d ai=%d alive=%d score=%d "
            "cities=%d pop_k=%d techs=%d techout=%d gold=%d bulbs=%d "
            "units=%d land=%d declares=%d blocked_attempts=%d "
            "blocked_unique=%d blocked_declare=%d blocked_attack=%d "
            "supp_pairs=%d supp_events=%d on_source=%d marks=%d "
            "marks_live=%d gone=%d rules=%d barb_marks=%d barb_rules=%d",
            game.info.turn, player_name(plr), me, dof_enabled(plr) ? 1 : 0,
            is_ai(plr) ? 1 : 0, plr->is_alive ? 1 : 0, plr->score.game,
            plr->score.cities, plr->score.population, plr->score.techs,
            plr->score.techout, plr->economic.gold, plr->server.bulbs_last_turn,
            plr->score.units, plr->score.landarea, dof_declares_seat[me],
            dof_blk_att_seat[me], dof_blk_uniq_seat[me],
            dof_blk_att[DOF_BLOCK_DECLARE], dof_blk_att[DOF_BLOCK_ATTACK],
            dof_supp_pairs_seat[me], dof_supp_events_seat[me],
            dof_on_source_seat[me], dof_marks_seat[me], live,
            dof_gone_seat[me], dof_rules_seat[me], dof_barb_marks,
            dof_barb_rules);
  } players_iterate_end;

  dof_log("totals_global turn=%d blocked_attempts_declare=%d "
          "blocked_unique_declare=%d blocked_attempts_attack=%d "
          "blocked_unique_attack=%d supp_pairs=%d supp_events=%d "
          "on_source=%d barb_marks=%d barb_rules=%d",
          game.info.turn, dof_blk_att[DOF_BLOCK_DECLARE],
          dof_blk_uniq[DOF_BLOCK_DECLARE], dof_blk_att[DOF_BLOCK_ATTACK],
          dof_blk_uniq[DOF_BLOCK_ATTACK], dof_supp_pairs, dof_supp_events,
          dof_attacks_on_source, dof_barb_marks, dof_barb_rules);
}

/**********************************************************************//**
  The current policy spec.
**************************************************************************/
const char *dof_policy_spec(void)
{
  return dof_policy.spec;
}
