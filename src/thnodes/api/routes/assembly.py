"""
GET /api/models/{model_id}/assembly

Rebuilds the system via the deterministic grouping rule (D3) and
Assembler.build(strict=False) on every call.
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
    SignalOut,
)
from ..store import (
    doc_to_group,
    get_doc,
    signal_to_out,
    _elem_label_to_id,
    _group_assembler_module_name_to_id,
)

router = APIRouter(prefix="/models/{model_id}")


@router.get("/assembly", response_model=AssemblyOut)
def get_assembly(model_id: str) -> AssemblyOut:
    doc = get_doc(model_id)

    try:
        gr = doc_to_group(doc)
        asm = gr.to_assembler()
        system, raw_problems = asm.build(strict=False)
    except Exception as exc:
        # Guard defensively so the endpoint never 500s.
        return AssemblyOut(
            ownership=[],
            parameters=[],
            states=[],
            signals=[],
            graph=GraphOut(nodes=[], edges=[]),
            problems=[ProblemOut(kind="internal_error", message=str(exc))],
            required_signals=[],
        )

    problems = [
        ProblemOut(
            kind=p.kind,
            message=p.message,
            cell=list(p.cell) if p.cell else None,
        )
        for p in raw_problems
    ]

    # required_signals: the set of Signals the derived modules demand.
    # Always derived from the grouping result, even when system is None.
    required_signals: list[SignalOut] = [
        signal_to_out(sig) for sig in gr.signals
    ]

    if system is None:
        return AssemblyOut(
            ownership=[],
            parameters=[],
            states=[],
            signals=[],
            graph=GraphOut(nodes=[], edges=[]),
            problems=problems,
            required_signals=required_signals,
        )

    # Maps for translating internal labels back to derived-module stable IDs
    label_to_eid = _elem_label_to_id(doc)
    # Mapping from Assembler-internal positional name to derived module stable ID
    mod_asmname_to_id = _group_assembler_module_name_to_id(gr)

    # Ownership table: (element_label, Channel) -> module_name
    ownership_list: list[OwnershipEntry] = []
    for (elem_label, ch), mod_name in system.ownership_map().items():
        eid = label_to_eid.get(elem_label, "")
        mid = mod_asmname_to_id.get(mod_name, mod_name)
        ownership_list.append(OwnershipEntry(
            element_id=eid,
            element_label=elem_label,
            channel=ch.name,
            module_id=mid,
        ))

    # Parameters with contributions
    contribs_by_param = system.parameter_contributions()

    # Build param→module_id mapping from derived modules.
    # Each derived module knows its params; find the stable ID for each.
    key_to_id = {dm.key: (
        f"{dm.key[0]}[{dm.key[1]}]" if dm.key[1] is not None else dm.key[0]
    ) for dm in gr.derived_modules}
    param_to_module_id: dict[str, str] = {}
    for dm in gr.derived_modules:
        stable_id = key_to_id[dm.key]
        for pname in dm.module.params:
            param_to_module_id[pname] = stable_id

    parameters: list[ParameterOut] = []
    for pname in system.param_names:
        mu_log, sigma_log = system.priors[pname]
        param_mid = param_to_module_id.get(pname, "")

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
        mid = mod_asmname_to_id.get(mod_name, mod_name)
        # Find the module instance to check private_states and signals.
        from_node = None
        for route_entry in asm._routes:
            mod_obj = route_entry[0]
            if mod_obj.name == mod_name:
                if mod_obj.private_states:
                    from_node = mod_obj.private_states[0]
                elif mod_obj.signals:
                    from_node = mod_obj.signals[0]
                break
        if from_node is None:
            from_node = "T_room"
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
        required_signals=required_signals,
    )
