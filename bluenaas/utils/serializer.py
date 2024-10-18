import json
from pathlib import Path

def serialize_template_params(params: any) -> str:
    # Convert Path to string and pydantic dataclass to dict
    data = {
        "template_filepath": str(params.template_filepath),
        "morph_filepath": str(params.morph_filepath),
        "template_format": params.template_format,
        "emodel_properties": params.emodel_properties.__dict__
        if params.emodel_properties
        else None,
    }
    return json.dumps(data)


# Deserialize JSON string back to TemplateParams
def deserialize_template_params(json_str: str):
    from bluecellulab.cell.template import TemplateParams, EmodelProperties

    data = json.loads(json_str)

    # Convert string back to Path and rebuild EmodelProperties dataclass
    template_filepath = Path(data["template_filepath"])
    morph_filepath = Path(data["morph_filepath"])

    emodel_properties_data = data["emodel_properties"]
    emodel_properties = None
    if emodel_properties_data:
        emodel_properties = EmodelProperties(
            threshold_current=emodel_properties_data["threshold_current"],
            holding_current=emodel_properties_data["holding_current"],
            AIS_scaler=emodel_properties_data.get("AIS_scaler", 1.0),
            soma_scaler=emodel_properties_data.get("soma_scaler", 1.0),
        )

    return TemplateParams(
        template_filepath=template_filepath,
        morph_filepath=morph_filepath,
        template_format=data["template_format"],
        emodel_properties=emodel_properties,
    )
