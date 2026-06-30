from fastapi import APIRouter

from ...registry import ELEMENT_TYPES, LAYER_SCHEMA, MODULE_TYPES
from ..models import ElementTypeOut, FieldSchemaOut, LayerSchemaOut, ModuleTypeOut, RegistryOut

router = APIRouter()


def _field_schema(f: dict) -> FieldSchemaOut:
    return FieldSchemaOut(
        name=f["name"],
        type=f["type"],
        default=f.get("default"),
        options=f.get("options"),
    )


@router.get("/registry", response_model=RegistryOut)
def get_registry() -> RegistryOut:
    element_types = [
        ElementTypeOut(
            type_name=tname,
            fields=[_field_schema(f) for f in info["fields"]],
            boundary=info.get("boundary"),
            treatments=info.get("treatments", []),
        )
        for tname, info in ELEMENT_TYPES.items()
    ]
    module_types = [
        ModuleTypeOut(
            type_name=tname,
            owns=info["owns"],
            params=info["params"],
            fields=[_field_schema(f) for f in info["fields"]],
        )
        for tname, info in MODULE_TYPES.items()
    ]
    layer_schema = LayerSchemaOut(
        fields=[_field_schema(f) for f in LAYER_SCHEMA["fields"]]
    )
    return RegistryOut(
        element_types=element_types,
        module_types=module_types,
        layer_schema=layer_schema,
    )
