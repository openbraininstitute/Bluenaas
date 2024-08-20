from bluenaas.core.stimulation import SynapseRecording
from bluenaas.domains.morphology import SynapseSeries
from bluenaas.domains.simulation import RecordingLocation, SimulationConditionsConfig
from bluenaas.utils.util import generate_pre_spiketrain


def _add_single_synapse(
    cell,
    synapse: SynapseSeries,
    conditions: SimulationConditionsConfig
):
    from bluecellulab.circuit.config.sections import Conditions  # type: ignore
    from bluecellulab.synapse.synapse_types import SynapseID  # type: ignore
    from bluecellulab import Connection

    condition_parameters = Conditions(
        celsius=conditions.celsius,
        v_init=conditions.vinit,
        randomize_gaba_rise_time=True,
    )
    synid = SynapseID(f"{synapse["id"]}", synapse["id"])
    # A tuple containing source and target popids used by the random number generation.
    # Should correspond to source_popid and target_popid
    popids = (2126, 378)
    connection_modifiers = {
        "add_synapses": True,
    }

    cell.add_replay_synapse(
        synapse_id=synid,
        syn_description=synapse["series"],
        connection_modifiers=connection_modifiers,
        condition_parameters=condition_parameters,
        popids=popids,
        extracellular_calcium=None,  # may not be value used in circuit
    )
    cell_synapse = cell.synapses[synid]

    spike_train = generate_pre_spiketrain(synapse["synapseSimulationConfig"])
    spike_threshold = -900.0  # TODO: Synapse - How to get spike threshold
    connection = Connection(
        cell_synapse,
        pre_spiketrain=spike_train,
        pre_cell=None,
        stim_dt=cell.record_dt,
        spike_threshold=spike_threshold,
        spike_location="soma[0]"
    )
    cell.connections[synid] = connection


def run_synaptome_simulation(
    template_params, synapse_series, recording_location: list[RecordingLocation]
) -> SynapseRecording:
    from bluecellulab.cell.core import Cell
    from bluecellulab.simulation import Simulation

    cell = Cell.from_template_parameters(template_params)

    recording_section = cell.sections[recording_location[0].section]
    recording_segment = recording_location[0].segment_offset

    for synapse in synapse_series:
        _add_single_synapse(cell, synapse)

    cell.add_voltage_recording(
        section=recording_section,
        segx=recording_segment,
    )

    sim = Simulation()
    sim.add_cell(cell)

    # TODO: fix the maxtime (user input or direct current injection maxtime)
    sim.run(160.0, cvode=False, dt=0.1)  # TODO: Synapse How to get duration
    time = cell.get_time()
    voltage = cell.get_voltage_recording(
        section=recording_section,
        segx=recording_segment,
    )
    print("Time", time)
    print("Voltage", voltage)

    if len(time) != len(voltage):
        raise ValueError("Time and voltage arrays are not the same length")

    recording = SynapseRecording(
        voltage, time
    )  # TODO: How to get current like we get in directInjectionConfig

    return recording
