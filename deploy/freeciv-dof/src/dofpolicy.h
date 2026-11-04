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
struct unit;

/* Turns during which an observed attacker keeps the collapse-source flag. */
#define DOF_SOURCE_HORIZON 20

/* Re-read the policy file if it changed. Safe to call often. */
void dof_policy_reload(void);

/* Is the DOF policy active for this player (seat)? */
bool dof_enabled(const struct player *pplayer);

/* Both seats of a pair carry the policy. Diplomatic state is pairwise, so a
 * rule that disables an engine-driven war may only apply when neither side is
 * a control seat. */
bool dof_pair_enabled(const struct player *one, const struct player *two);

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

/* Is THIS unit a collapse source for "pplayer"? The unit itself performed an
 * attack on somebody "pplayer" knows and is still alive: the source of
 * collapse is the unit, not the nation. */
bool dof_unit_is_source(const struct player *pplayer,
                        const struct unit *punit);

/* How many living marked units of "owner" does "pplayer" know about? */
int dof_source_unit_count(const struct player *pplayer,
                          const struct player *owner);

/* Remember the unit that performs the current action (server/unithand.c). */
void dof_set_acting_unit(const struct unit *punit);

/* An attack performed by a unit on a player, recorded with the unit itself.
 * War-time attacks carry no casus belli, so this is the only way the ledger
 * learns which units keep attacking. */
void dof_note_unit_attack(const struct unit *punit, struct player *victim);

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

/* End-of-game totals: one journal line per seat with every counter
 * (attempts and unique events for blocked acts, suppressed pairs and events,
 * marks, declares). Complete where the event stream is sampled. Called once
 * from server/srv_main.c in srv_scores(). */
void dof_totals_report(void);

/* Rule set carried by a DOF seat. A preset picks a subset: "full" is the
 * behaviour every published series used; the others isolate one rule, so that
 * an effect can be attributed to that rule and not to the concept as a whole.
 * Spec syntax in the policy file: <seat selector>[:<preset>], for example
 * "even:ban", "all:nocoerce", "0,3,6:nowarblock". No preset means "full". */
#define DOF_F_BAN        (1u << 0)  /* no war desire, no declaration, no revenge */
#define DOF_F_ATTACK     (1u << 1)  /* no attack on a non-source (unit level) */
#define DOF_F_SELFDEF    (1u << 2)  /* answer an attack on this seat */
#define DOF_F_SOLIDARITY (1u << 3)  /* answer an attack on a known third party */
#define DOF_F_COERCE     (1u << 4)  /* no bribe/sabotage/poison/spy nuke */
#define DOF_F_UNKNOWN    (1u << 5)  /* an unmet player is not a target */
#define DOF_F_RAMPAGE    (1u << 6)  /* marked units are hunted first */
#define DOF_F_CEASEFIRE  (1u << 7)  /* peace without ransom; expiry is peace */
#define DOF_F_SPACE      (1u << 8)  /* no war to stop a space race */
#define DOF_F_NO_TARGET  (1u << 9)  /* no war because nothing else is left */
#define DOF_F_ALLY_WAR   (1u << 10) /* no joining a war for an ally */
#define DOF_F_NO_MERCY   (1u << 11) /* peace is offered even to the target */
#define DOF_F_FULL       0x00000FFFu

/* Which rules this seat carries (0 for a classic seat). */
unsigned dof_flags(const struct player *pplayer);

/* Is this one rule on for this seat? */
bool dof_flag(const struct player *pplayer, unsigned flag);

/* Current policy spec, for logging/reporting. */
const char *dof_policy_spec(void);

#ifdef __cplusplus
}
#endif /* __cplusplus */

#endif /* FC__DOFPOLICY_H */
