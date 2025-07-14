from enum import StrEnum


# ! This has to be in sync with the functions in the jobs/handlers folder
class JobFn(StrEnum):
    # Single neuron
    GENERATE_SINGLE_NEURON_SYNAPTOME = "app.job.handlers.single_neuron.synaptome.generate_synapses"
    GET_SINGLE_NEURON_CURRENT_CLAMP_PLOT_DATA = (
        "app.job.handlers.single_neuron.current_clamp_plot.get_current_clamp_plot_data"
    )
    GET_SINGLE_NEURON_MORPHOLOGY = "app.job.handlers.single_neuron.morphology.get_morphology"
    GET_SINGLE_NEURON_MORPHOLOGY_DENDROGRAM = (
        "app.job.handlers.single_neuron.morphology.get_morphology_dendrogram"
    )
    RUN_SINGLE_NEURON_CALIBRATION = "app.job.handlers.single_neuron.calibration.run"
    RUN_SINGLE_NEURON_SIMULATION = "app.job.handlers.single_neuron.simulation.run"
    RUN_SINGLE_NEURON_VALIDATION = "app.job.handlers.single_neuron.validation.run"
    SETUP_SINGLE_NEURON_SIMULATION_RESOURCES = (
        "app.job.handlers.single_neuron.simulation_resources.setup_simulation_resources"
    )

    # Circuit
    RUN_CIRCUIT_SIMULATION = "app.job.handlers.circuit.simulation.run_circuit_simulation"
