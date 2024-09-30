from bluenaas.domains.morphology import SynapseSeries


def serialize_stimulus(stimulus: any) -> dict:
    return {
        "dt": stimulus.dt,
        "time": stimulus.time.tolist(),  # Convert np.ndarray to list
        "current": stimulus.current.tolist(),  # Convert np.ndarray to list
    }


def serialize_template_params(obj: any) -> dict:
    """Converts TemplateParams to a JSON-serializable dictionary."""
    return {
        "template_filepath": str(obj.template_filepath),  # Convert Path to string
        "morph_filepath": str(obj.morph_filepath),  # Convert Path to string
        "template_format": obj.template_format,
        "emodel_properties": None
        if obj.emodel_properties is None
        else {
            "threshold_current": obj.emodel_properties.threshold_current,
            "holding_current": obj.emodel_properties.holding_current,
            "AIS_scaler": obj.emodel_properties.AIS_scaler,
            "soma_scaler": obj.emodel_properties.soma_scaler,
        },
    }


def serialize_synapse_series(synapse_config: SynapseSeries) -> dict:
    return {
        "id": synapse_config["id"],
        "series": synapse_config["series"].tolist(),  # Convert pandas.Series to a list
        "directCurrentConfig": {
            "amplitude": synapse_config["directCurrentConfig"].amplitude
        },  # Convert custom object to a dictionary
        "synapseSimulationConfig": {
            "duration": synapse_config["synapseSimulationConfig"].duration
        },  # Convert custom object to a dictionary
        "frequencies_to_apply": synapse_config["frequencies_to_apply"],
    }
