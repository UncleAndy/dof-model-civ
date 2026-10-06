"""Неполнота решения (§4.7, §6.2): что модель не измерила — объявлено, а не умолчано.

Буква §6.2: `unknown_resources` — ресурсы с `value = null`, которые **не были разрешены
ни одним кандидатом**, списком `{ resource_id, used_estimated, has_fallback }`;
`incomplete` — резолвимый неизвестный (`t* > 0`) остался не измеренным ни в одном
отобранном кандидате, и тогда решение объявлено неполным, а не выданным за информированное.

В нашей модели ни одна сущность не имеет `dof_known == false` — линзы измеряются все, —
поэтому поле ядра, определённое через сущности, молчит не потому, что неполноты нет, а
потому, что её носители другие: не измерены **входы**. Мы ведём то же правило по
объявленным неизвестным входам (`SPEC_UNKNOWN_INPUTS`) и называем причины поимённо.

Флаг — поле отчёта, а не вход в счёт: он не появляется ни в одной опции и не меняет ни
индекса, ни выбора (проверяется сторожем I20).
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from env.config import SPEC_T_MEAS_MKS, SPEC_UNKNOWN_INPUTS


def unknown_resources(options: Iterable[object],
                      declared: Sequence[Mapping[str, object]] = SPEC_UNKNOWN_INPUTS
                      ) -> list[dict[str, object]]:
    """§6.2: неизвестные входы и то, разрешил ли их какой-нибудь кандидат."""
    rows: list[dict[str, object]] = []
    opts = list(options)
    for item in declared:
        uid = str(item.get("id"))
        resolved = [str(getattr(o, "option_id", o)) for o in opts
                    if uid in (getattr(o, "discovers", None) or [])]
        rows.append({
            "resource_id": uid,
            "used_estimated": bool(item.get("used_estimated", False)),
            "has_fallback": bool(item.get("has_fallback", False)),
            "why": item.get("why"),
            "measurable_on": item.get("measurable_on"),
            "resolved_by": resolved,
        })
    return rows


def completeness(options: Iterable[object],
                 declared: Sequence[Mapping[str, object]] = SPEC_UNKNOWN_INPUTS,
                 t_meas: tuple[float, float] | None = SPEC_T_MEAS_MKS) -> dict:
    """§4.7/§6.2: объявлена ли неполнота. Причина называется, а не подразумевается.

    Две причины, обе по букве: (1) неизвестный вход не разрешён ни одним кандидатом
    (§6.2, §4.8: неизвестное без оценки — недопустимый вход для гейта платежа);
    (2) длительности измерения `t_m`, `t_v` не объявлены — по §4.7 отчёт состояния,
    не объявившего их, **неполон**, а не подставляет нули.
    """
    rows = unknown_resources(options, declared)
    unresolved = [str(r["resource_id"]) for r in rows if not r["resolved_by"]]
    reasons: list[str] = []
    if unresolved:
        reasons.append("неизвестный вход не разрешён ни одним кандидатом: "
                       + ", ".join(unresolved)
                       + " (цена технологии мир не публикует)")
    if t_meas is None:
        reasons.append("длительности измерения `t_m`, `t_v` не объявлены — отчёт неполон "
                       "по §4.7, а не подставляет нули")
    return {
        "incomplete": bool(reasons),
        "unknown_resources": rows,
        "binding": unresolved,
        "reasons": reasons,
    }
