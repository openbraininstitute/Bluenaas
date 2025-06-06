from enum import StrEnum


# ! This has to be in sync with the functions in the jobs/handlers folder
class JobFn(StrEnum):
    GET_MORPHOLOGY = "app.job.handlers.single_cell.morphology.get_morphology"
    GET_CURRENT_CLAMP_PLOT_DATA = (
        "app.job.handlers.single_cell.current_clamp.get_current_clamp_plot_data"
    )
    RUN_SINGLE_NEURON_SIMULATION = (
        "app.job.handlers.single_cell.simulation.run_single_neuron_simulation"
    )
