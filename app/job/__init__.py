from enum import StrEnum


# ! This has to be in sync with the functions in the jobs/handlers folder
class JobFn(StrEnum):
    GET_MORPHOLOGY = "app.job.handlers.single_neuron.morphology.get_morphology"
    GET_MORPHOLOGY_DENDROGRAM = (
        "app.job.handlers.single_neuron.morphology.get_morphology_dendrogram"
    )
    GET_CURRENT_CLAMP_PLOT_DATA = (
        "app.job.handlers.single_neuron.current_clamp_plot.get_current_clamp_plot_data"
    )
    RUN_SINGLE_NEURON_SIMULATION = "app.job.handlers.single_neuron.simulation.run"
    GENERATE_SYNAPSES = "app.job.handlers.single_neuron.synaptome.generate_synapses"
    RUN_CIRCUIT_SIMULATION = (
        "app.job.handlers.circuit.simulation.run_circuit_simulation"
    )
    SETUP_SIMULATION_RESOURCES = (
        "app.job.handlers.single_neuron.simulation_resources.setup_simulation_resources"
    )
