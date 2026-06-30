from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ...draw import topology_svg
from ..store import get_doc, doc_to_group

router = APIRouter(prefix="/models/{model_id}")


@router.get("/topology.svg")
def get_topology_svg(model_id: str) -> Response:
    doc = get_doc(model_id)

    gr = doc_to_group(doc)
    asm = gr.to_assembler()
    system, problems = asm.build(strict=False)
    if system is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot render topology: room is incomplete. "
            + "; ".join(p.message for p in problems),
        )

    # topology_svg returns SVG bytes (schemdraw renders via matplotlib's SVG backend)
    img_bytes = topology_svg(system)
    return Response(content=img_bytes, media_type="image/svg+xml")
