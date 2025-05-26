from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import UUID4, BaseModel, Field, RootModel


class Annotation(BaseModel):
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    id: UUID = Field(..., title="Id")
    pref_label: str = Field(..., title="Pref Label")
    alt_label: str = Field(..., title="Alt Label")
    definition: str = Field(..., title="Definition")


class AssetLabel(Enum):
    neurolucida = "neurolucida"
    swc = "swc"
    hdf5 = "hdf5"
    cell_composition_summary = "cell_composition_summary"
    cell_composition_volumes = "cell_composition_volumes"
    single_neuron_synaptome_config = "single_neuron_synaptome_config"
    single_neuron_synaptome_simulation_io_result = (
        "single_neuron_synaptome_simulation_io_result"
    )


class AssetStatus(Enum):
    created = "created"
    deleted = "deleted"


class BrainRegionRead(BaseModel):
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    id: UUID = Field(..., title="Id")
    annotation_value: int = Field(..., title="Annotation Value")
    name: str = Field(..., title="Name")
    acronym: str = Field(..., title="Acronym")
    color_hex_triplet: str = Field(..., title="Color Hex Triplet")
    parent_structure_id: Optional[UUID] = Field(..., title="Parent Structure Id")
    hierarchy_id: UUID = Field(..., title="Hierarchy Id")


class EntityRoute(Enum):
    analysis_software_source_code = "analysis-software-source-code"
    brain_atlas = "brain-atlas"
    emodel = "emodel"
    cell_composition = "cell-composition"
    experimental_bouton_density = "experimental-bouton-density"
    experimental_neuron_density = "experimental-neuron-density"
    experimental_synapses_per_connection = "experimental-synapses-per-connection"
    memodel = "memodel"
    mesh = "mesh"
    me_type_density = "me-type-density"
    reconstruction_morphology = "reconstruction-morphology"
    electrical_cell_recording = "electrical-cell-recording"
    electrical_recording_stimulus = "electrical-recording-stimulus"
    single_neuron_simulation = "single-neuron-simulation"
    single_neuron_synaptome = "single-neuron-synaptome"
    single_neuron_synaptome_simulation = "single-neuron-synaptome-simulation"
    ion_channel_model = "ion-channel-model"
    subject = "subject"


class EntityType(Enum):
    analysis_software_source_code = "analysis_software_source_code"
    brain_atlas = "brain_atlas"
    emodel = "emodel"
    cell_composition = "cell_composition"
    experimental_bouton_density = "experimental_bouton_density"
    experimental_neuron_density = "experimental_neuron_density"
    experimental_synapses_per_connection = "experimental_synapses_per_connection"
    memodel = "memodel"
    mesh = "mesh"
    me_type_density = "me_type_density"
    reconstruction_morphology = "reconstruction_morphology"
    electrical_cell_recording = "electrical_cell_recording"
    electrical_recording_stimulus = "electrical_recording_stimulus"
    single_neuron_simulation = "single_neuron_simulation"
    single_neuron_synaptome = "single_neuron_synaptome"
    single_neuron_synaptome_simulation = "single_neuron_synaptome_simulation"
    ion_channel_model = "ion_channel_model"
    subject = "subject"


class LicenseRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    label: str = Field(..., title="Label")


class OrganizationRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    pref_label: str = Field(..., title="Pref Label")
    alternative_name: Optional[str] = Field(None, title="Alternative Name")
    type: str = Field(..., title="Type")


class PersonRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    given_name: Optional[str] = Field(None, title="Given Name")
    family_name: Optional[str] = Field(None, title="Family Name")
    pref_label: str = Field(..., title="Pref Label")
    type: str = Field(..., title="Type")


class PointLocationBase(BaseModel):
    x: float = Field(..., title="X")
    y: float = Field(..., title="Y")
    z: float = Field(..., title="Z")


class RoleRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    role_id: str = Field(..., title="Role Id")


class SingleNeuronSimulationStatus(Enum):
    started = "started"
    failure = "failure"
    success = "success"


class NestedSynaptome(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    seed: int = Field(..., title="Seed")


class SingleNeuronSynaptomeSimulationRead(BaseModel):
    assets: list["AssetRead"] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    id: UUID = Field(..., title="Id")
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    brain_region: BrainRegionRead
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    seed: int = Field(..., title="Seed")
    status: SingleNeuronSimulationStatus
    injectionLocation: List[str] = Field(..., title="Injectionlocation")
    recordingLocation: List[str] = Field(..., title="Recordinglocation")
    synaptome: NestedSynaptome


class SpeciesRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    taxonomy_id: str = Field(..., title="Taxonomy Id")


class StrainRead(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    taxonomy_id: str = Field(..., title="Taxonomy Id")
    species_id: UUID = Field(..., title="Species Id")


class UseIon(BaseModel):
    ion_name: str = Field(..., title="Ion Name")
    read: Optional[List[str]] = Field([], title="Read")
    write: Optional[List[str]] = Field([], title="Write")
    valence: Optional[int] = Field(None, title="Valence")
    main_ion: Optional[bool] = Field(None, title="Main Ion")


class ValidationStatus(Enum):
    created = "created"
    initialized = "initialized"
    running = "running"
    done = "done"
    error = "error"


class AgentRead(RootModel[PersonRead | OrganizationRead]):
    pass


class AssetRead(BaseModel):
    path: str = Field(..., title="Path")
    full_path: str = Field(..., title="Full Path")
    is_directory: bool = Field(..., title="Is Directory")
    content_type: str = Field(..., title="Content Type")
    size: int = Field(..., title="Size")
    sha256_digest: Optional[str] = Field(..., title="Sha256 Digest")
    meta: Dict[str, Any] = Field(..., title="Meta")
    label: Optional[AssetLabel] = None
    id: UUID = Field(..., title="Id")
    status: AssetStatus


class ContributionReadWithoutEntity(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    agent: AgentRead
    role: RoleRead


class ExemplarMorphology(BaseModel):
    id: UUID = Field(..., title="Id")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    location: Optional[PointLocationBase]
    legacy_id: Optional[List[str]] = Field(..., title="Legacy Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")


class NestedMEModel(BaseModel):
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    validation_status: Optional[ValidationStatus] = ValidationStatus.created
    holding_current: Optional[float] = Field(None, title="Holding Current")
    threshold_current: Optional[float] = Field(None, title="Threshold Current")
    mtypes: Optional[List[Annotation]] = Field(..., title="Mtypes")
    etypes: Optional[List[Annotation]] = Field(..., title="Etypes")


class NeuronBlock(BaseModel):
    global_: Optional[List[Dict[str, Optional[str]]]] = Field(
        [], alias="global", title="Global"
    )
    range: Optional[List[Dict[str, Optional[str]]]] = Field([], title="Range")
    useion: Optional[List[UseIon]] = Field([], title="Useion")
    nonspecific: Optional[List[Dict[str, Optional[str]]]] = Field(
        [], title="Nonspecific"
    )


class ReconstructionMorphologyRead(BaseModel):
    type: Optional[EntityType] = None
    assets: list[AssetRead] = Field(..., title="Assets")
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    license: Optional[LicenseRead]
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    location: Optional[PointLocationBase]
    legacy_id: Optional[List[str]] = Field(..., title="Legacy Id")
    species: SpeciesRead
    strain: Optional[StrainRead]
    brain_region: BrainRegionRead
    contributions: Optional[List[ContributionReadWithoutEntity]] = Field(
        ..., title="Contributions"
    )
    mtypes: Optional[List[Annotation]] = Field(..., title="Mtypes")


class SingleNeuronSimulationRead(BaseModel):
    assets: list[AssetRead] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    id: UUID = Field(..., title="Id")
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    brain_region: BrainRegionRead
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    seed: int = Field(..., title="Seed")
    status: SingleNeuronSimulationStatus
    injectionLocation: List[str] = Field(..., title="Injectionlocation")
    recordingLocation: List[str] = Field(..., title="Recordinglocation")
    me_model: NestedMEModel


class SingleNeuronSynaptomeRead(BaseModel):
    assets: list[AssetRead] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    contributions: Optional[List[ContributionReadWithoutEntity]] = Field(
        ..., title="Contributions"
    )
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    id: UUID = Field(..., title="Id")
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    seed: int = Field(..., title="Seed")
    me_model: NestedMEModel
    brain_region: BrainRegionRead
    created_by: Optional[PersonRead]
    updated_by: Optional[PersonRead]


class EModelRead(BaseModel):
    assets: list[AssetRead] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    description: str = Field(..., title="Description")
    name: str = Field(..., title="Name")
    iteration: str = Field(..., title="Iteration")
    score: float = Field(..., title="Score")
    seed: int = Field(..., title="Seed")
    id: UUID = Field(..., title="Id")
    species: SpeciesRead
    strain: Optional[StrainRead]
    brain_region: BrainRegionRead
    contributions: Optional[List[ContributionReadWithoutEntity]] = Field(
        ..., title="Contributions"
    )
    mtypes: Optional[List[Annotation]] = Field(..., title="Mtypes")
    etypes: Optional[List[Annotation]] = Field(..., title="Etypes")
    exemplar_morphology: ExemplarMorphology


class IonChannelModelWAssets(BaseModel):
    assets: list[AssetRead] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    id: UUID = Field(..., title="Id")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    description: str = Field(..., title="Description")
    name: str = Field(..., title="Name")
    nmodl_suffix: str = Field(..., title="Nmodl Suffix")
    is_ljp_corrected: Optional[bool] = Field(False, title="Is Ljp Corrected")
    is_temperature_dependent: Optional[bool] = Field(
        False, title="Is Temperature Dependent"
    )
    temperature_celsius: int = Field(..., title="Temperature Celsius")
    is_stochastic: Optional[bool] = Field(False, title="Is Stochastic")
    neuron_block: NeuronBlock
    species: SpeciesRead
    strain: Optional[StrainRead]
    brain_region: BrainRegionRead


class MEModelRead(BaseModel):
    type: Optional[EntityType] = None
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    validation_status: Optional[ValidationStatus] = ValidationStatus.created
    holding_current: Optional[float] = Field(None, title="Holding Current")
    threshold_current: Optional[float] = Field(None, title="Threshold Current")
    id: UUID = Field(..., title="Id")
    species: SpeciesRead
    strain: Optional[StrainRead]
    brain_region: BrainRegionRead
    contributions: Optional[List[ContributionReadWithoutEntity]] = Field(
        ..., title="Contributions"
    )
    mtypes: Optional[List[Annotation]] = Field(..., title="Mtypes")
    etypes: Optional[List[Annotation]] = Field(..., title="Etypes")
    morphology: ReconstructionMorphologyRead
    emodel: EModelRead


class EModelReadExpanded(BaseModel):
    assets: list[AssetRead] = Field(..., title="Assets")
    type: Optional[EntityType] = None
    authorized_project_id: UUID4 = Field(..., title="Authorized Project Id")
    authorized_public: Optional[bool] = Field(False, title="Authorized Public")
    creation_date: datetime = Field(..., title="Creation Date")
    update_date: datetime = Field(..., title="Update Date")
    description: str = Field(..., title="Description")
    name: str = Field(..., title="Name")
    iteration: str = Field(..., title="Iteration")
    score: float = Field(..., title="Score")
    seed: int = Field(..., title="Seed")
    id: UUID = Field(..., title="Id")
    species: SpeciesRead
    strain: Optional[StrainRead]
    brain_region: BrainRegionRead
    contributions: Optional[List[ContributionReadWithoutEntity]] = Field(
        ..., title="Contributions"
    )
    mtypes: Optional[List[Annotation]] = Field(..., title="Mtypes")
    etypes: Optional[List[Annotation]] = Field(..., title="Etypes")
    exemplar_morphology: ExemplarMorphology
    ion_channel_models: List[IonChannelModelWAssets] = Field(
        ..., title="Ion Channel Models"
    )
