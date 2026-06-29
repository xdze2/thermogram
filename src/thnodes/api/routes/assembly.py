"""
GET /api/models/{model_id}/assembly

Rebuilds the system via Assembler.build(strict=False) on every call.
Never returns HTTP 500 — partial data + problems[] is always returned.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models import (
    AssemblyOut,
    ContributionOut,
    GraphOut,
    GraphNode,
    OwnershipEntry,
    ParameterOut,
    PriorOut,
    ProblemOut,
)
from ..store import get_doc, roomboc_to_assembler, _elem_label_to_id, _module_name_to_id

router = APIRouter(prefix="/models/{model_id}")


@router.get("/assembly", response_model=AssemblyOut)
def get_assembly(model_id: str) -> AssemblyOut:
    doc = get_doc(model_id)

    try:
        asm = roomboc_to_assembler(doc)
        system, raw_problems = asm.build(strict=False)
    except Exception as exc:
        # Assembler construction itself shouldn't raise (build strict=False catches all),
        # but guard defensively so the endpoint never 500s.
        return AssemblyOut(
            ownership=[],
            parameters=[],
            states=[],
            signals=[],
            graph=GraphOut(nodes=[], edges=[]),
            problems=[ProblemOut(kind="internal_error", message=str(exc))],
        )

    problems = [
        ProblemOut(
            kind=p.kind,
            message=p.message,
            cell=list(p.cell) if p.cell else None,
        )
        for p in raw_problems
    ]

    if system is None:
        return AssemblyOut(
            ownership=[],
            parameters=[],
            states=[],
            signals=[],
            graph=GraphOut(nodes=[], edges=[]),
            problems=problems,
        )

    # Maps for translating internal labels back to session IDs
    label_to_eid = _elem_label_to_id(doc)
    mod_name_to_mid = _module_name_to_id(doc)

    # Ownership table: (element_label, Channel) -> module_name
    ownership_list: list[OwnershipEntry] = []
    for (elem_label, ch), mod_name in system.ownership_map().items():
        eid = label_to_eid.get(elem_label, "")
        mid = mod_name_to_mid.get(mod_name, "")
        ownership_list.append(OwnershipEntry(
            element_id=eid,
            element_label=elem_label,
            channel=ch.name,
            module_id=mid,
        ))

    # Parameters with contributions
    contribs_by_param = system.parameter_contributions()
    parameters: list[ParameterOut] = []
    for pname in system.param_names:
        mu_log, sigma_log = system.priors[pname]

        # Find which module owns this param
        param_mid = ""
        for mid, spec in doc.modules.items():
            from ...registry import MODULE_TYPES
            if pname in MODULE_TYPES.get(spec.type, {}).get("params", []):
                param_mid = mid
                break

        raw_contribs = contribs_by_param.get(pname, [])
        contrib_out = [
            ContributionOut(
                element_id=label_to_eid.get(c["element_label"], ""),
                element_label=c["element_label"],
                channel=c["channel"],
                budget_field=c["budget_field"],
                value=c["value"],
            )
            for c in raw_contribs
        ]

        parameters.append(ParameterOut(
            name=pname,
            module_id=param_mid,
            prior=PriorOut(mu_log=mu_log, sigma_log=sigma_log),
            contributions=contrib_out,
        ))

    # Graph
    nodes: list[GraphNode] = [GraphNode(id="T_room", kind="room")]
    for sname in system.state_names[:-1]:  # private states (exclude T_room)
        nodes.append(GraphNode(id=sname, kind="state"))
    for sig in system.signal_names:
        nodes.append(GraphNode(id=sig, kind="boundary"))

    edges: list[dict] = []
    for (elem_label, ch), mod_name in system.ownership_map().items():
        mid = mod_name_to_mid.get(mod_name, "")
        # Determine the "from" node: private-state modules connect state→room;
        # boundary-signal modules connect signal→room.
        from_node = None
        # Find the module object to check private_states and signals
        for m in asm._routes:
            if m[0].name == mod_name:
                mod_obj = m[0]
                if mod_obj.private_states:
                    from_node = mod_obj.private_states[0]
                elif mod_obj.signals:
                    # Use the first boundary signal as the "from" node
                    from_node = mod_obj.signals[0]
                break
        if from_node is None:
            from_node = "T_room"
        # Deduplicate edges per (from_node, module_id)
        edge = {"from": from_node, "to": "T_room", "module_id": mid}
        if edge not in edges:
            edges.append(edge)

    graph = GraphOut(nodes=nodes, edges=edges)

    return AssemblyOut(
        ownership=ownership_list,
        parameters=parameters,
        states=system.state_names,
        signals=system.signal_names,
        graph=graph,
        problems=problems,
    )
