/***********************************************************************
 DOF-Core policy layer for the built-in freeciv AI (contact with strangers).

 Principle: DOF-Core, https://github.com/UncleAndy/dof-core
 Description of every engine change: DOF-AGENT.md / drafts/DOF_ENGINE_CHANGES.md

 The classic branch stays byte-identical when the policy is "none" (the
 control arm of an A/B): every gate below is a no-op for a classic seat.

 Doctrine (single source, must match .hermes.md of DOF-MODEL-CIV):
  * a peaceful foreign player ADDS to the common DoF, it is not a threat;
  * a player becomes a collapse source only by an OBSERVED first attack on a
    city or a unit of ANY player (not only ours);
  * SOLIDARITY: an agent that knows both sides (it has met the attacker and
    the victim) acts against the attacker even when it was not the victim;
  * the defender of that event is never marked;
  * the flag holds for DOF_SOURCE_HORIZON turns;
  * unknown is not zero: an unmet player is UNKNOWN, not hostile, and an
    attack whose victim the agent has never met is not a judgement it can make.

 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 2, or (at your option)
 any later version.
***********************************************************************/

#ifndef FC__DOFPOLICY_H
#define FC__DOFPOLICY_H

#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */

/* common */
#include "fc_types.h"

struct player;
struct action;

/* Turns during which an observed attacker keeps the collapse-source flag. */
#define DOF_SOURCE_HORIZON 20

/* Re-read the policy file if it changed. Safe to call often. */
void dof_policy_reload(void);

/* Is the DOF policy active for this player (seat)? */
bool dof_enabled(const struct player *pplayer);

/* Is "other" a collapse source from the point of view of "pplayer"?
 * A source is a player observed attacking somebody "pplayer" knows and has
 * met itself, so self-defence and solidarity are the same judgement. */
bool dof_is_source(const struct player *pplayer,
                   const struct player *other);

/* Is "other" a source for "pplayer" because of an attack on a THIRD party
 * (not on "pplayer")? Separates a war of solidarity from self-defence in the
 * journal. */
bool dof_source_is_third_party(const struct player *pplayer,
                               const struct player *other);

/* Journal: first contact with a stranger. */
void dof_journal_contact(struct player *pplayer, struct player *other);

/* Journal: the policy stopped an action that the classic arm would have taken.
 * This is the instrument for "how often does the rule bite". */
void dof_journal_blocked(struct player *pplayer, const struct player *other,
                         const char *what);

/* Journal: the policy acted on the doctrine (war on a source, ceasefire…). */
void dof_journal_rule(struct player *pplayer, const struct player *other,
                      const char *what);

/* Counter of turns on which the war desire was suppressed for a pair. Logs
 * once per pair and keeps the number for the summary. */
void dof_count_suppressed(const struct player *pplayer,
                          const struct player *other);

/* Journal: a war declaration by an AI (both arms, with the seat flag). */
void dof_journal_declare(struct player *pplayer, const struct player *other,
                         int reason);

/* Journal + ledger: an incident reported by the server. */
void dof_ledger_note(int type, const struct action *paction,
                     struct player *violator, struct player *victim);

/* AI console: "/aicmd <player> dof on|off|status". */
void dof_player_console(struct player *pplayer, const char *cmd);

/* Current policy spec, for logging/reporting. */
const char *dof_policy_spec(void);

#ifdef __cplusplus
}
#endif /* __cplusplus */

#endif /* FC__DOFPOLICY_H */
