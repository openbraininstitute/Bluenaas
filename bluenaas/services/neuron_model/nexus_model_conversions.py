from loguru import logger
from bluenaas.domains.neuron_model import (
    UsedModel,
    MEModelResponse,
    NexusMModelType,
    NexusEModelType,
    SynaptomeModelResponse,
    SynapseConfig,
)
from bluenaas.domains.simulation import BrainRegion


def nexus_me_model_to_bluenaas_me_model(nexus_model: dict) -> MEModelResponse:
    try:
        m_type = None
        e_type = None

        for part in nexus_model["hasPart"]:
            if part["@type"] == NexusMModelType:
                m_type = UsedModel(id=part["@id"], type="m-model", name=part["name"])
            elif part["@type"] == NexusEModelType:
                e_type = UsedModel(id=part["@id"], type="e-model", name=part["name"])

        assert m_type is not None
        assert e_type is not None

        brain_region = nexus_model["brainLocation"]["brainRegion"]
        me_model = MEModelResponse(
            id=nexus_model["_self"],
            name=nexus_model["name"],
            description=nexus_model.get("description"),
            type="me-model",
            created_by=nexus_model["_createdBy"],
            created_at=nexus_model["_createdAt"],
            brain_region=BrainRegion(
                id=brain_region["@id"], label=brain_region["label"]
            ),
            m_model=m_type,
            e_model=e_type,
        )

        return me_model
    except Exception:
        logger.exception(
            f"Nexus model could not be converted to me_model {nexus_model}"
        )
        raise ValueError(
            f"Cannot process incompatible nexus me model {nexus_model["_self"]}."
        )


def nexus_synaptome_model_to_bluenaas_synaptome_model(
    nexus_model: dict, distribution: dict
) -> SynaptomeModelResponse:
    try:
        synapses = distribution["synapses"]
        me_model_self = distribution["meModelSelf"]
        brain_region = nexus_model["brainLocation"]["brainRegion"]

        return SynaptomeModelResponse(
            id=nexus_model["_self"],
            name=nexus_model["name"],
            description=nexus_model.get("description"),
            type="synaptome",
            created_by=nexus_model["_createdBy"],
            created_at=nexus_model["_createdAt"],
            brain_region=BrainRegion(
                id=brain_region["@id"], label=brain_region["label"]
            ),
            me_model=UsedModel(
                id=me_model_self,
                type="me-model",
                name=nexus_model["used"]["name"],
            ),
            synapses=[SynapseConfig.model_validate(synapse) for synapse in synapses],
        )
    except Exception:
        logger.exception(
            f"Nexus model could not be converted to synaptome model {nexus_model}"
        )
        raise ValueError(
            f"Cannot process incompatible nexus synaptome model {nexus_model["_self"]}."
        )
