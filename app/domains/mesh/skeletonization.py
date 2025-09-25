from pydantic import BaseModel, Field

from entitysdk.models import ReconstructionMorphology


class SkeletonizationInputParams(BaseModel):
    name: str = Field(..., description="The name of the reconstructed morphology.")
    description: str = Field(..., description="A description of the reconstructed morphology.")


class SkeletonizationUltraliserParams(BaseModel, extra="forbid"):
    export_swc_morphology: bool | None = Field(
        None, description="Exports the neuronal morphology to .SWC file."
    )
    fix_soma_slicing_artifacts: bool | None = Field(
        None,
        description="Fix the slicing artifacts along the soma before the skeletonization of the neuron to ensure that the neuron has a valid graph. This option is highly recommended if the soma has obvious slicing artifacts.",
    )
    soma_segmentation_radius_threshold: float | None = Field(
        None, description="The Default value is 2.0 microns."
    )
    soma_segmenter_vpm: float | None = Field(
        None,
        description="Number of voxels per micron for the SomaSegmenter that is used to reconstruct a valid soma even if the input neuron mesh has slicing artifacts. Default value is 5.",
    )
    hq_vpm: float | None = Field(
        None,
        description="Number of voxels per micron for the the high quality resolution reconstructions. Default value is 20.",
    )
    export_optimized_neuron_mesh: bool | None = Field(
        None, description="Exports an optimized mesh of the input neuron."
    )
    export_soma_mesh: bool | None = Field(None, description="Exports segmented soma mesh.")
    export_proxy_soma_mesh: bool | None = Field(
        None,
        description="Exports the proxy mesh of the segmented soma. This mesh is mainly used for debugging. For a better mesh, use the --export-soma-mesh flag.",
    )
    debug_skeletonization: bool | None = Field(
        None,
        description="Debug the skeletonization by generating the artifacts at every stage of the process.",
    )
    resample_skeleton: bool | None = Field(
        None,
        description="Resample the section to remove unnecessary samples to export an optimum morphology.",
    )
    remove_spines_from_skeleton: bool | None = Field(
        None,
        description="Removes the spines and export only the branches of the the neuronal morphology to the .SWC file.",
    )
    spines_vpm: float | None = Field(
        None,
        description="Number of voxels per micron used to segment the spines. If this flag is set, then resolution will be ignored. Default value 25 vpm.",
    )
    export_dendritic_spines_proxy_meshes: bool | None = Field(
        None,
        description="Exports the proxy meshes of the segmented dendritic spines. The locations of these spine meshes will be on the dendrites.",
    )
    export_dendritic_spines_meshes: bool | None = Field(
        None,
        description="Exports the meshes of the segmented dendritic spines. The locations of these spine meshes will be on the dendrites.",
    )
    export_spines_meshes: bool | None = Field(
        None,
        description="Exports the meshes of the segmented spines. The locations of these spine meshes will be at the origin.",
    )
    export_spine_morphologies: bool | None = Field(
        None, description="Exports the morphologies of the spines to .SWC files."
    )
    ignore_morphology_prunning: bool | None = Field(
        None, description="Ignore the morphology prunning step and export the morphology as it is."
    )
    export_hq_neuron_mesh: bool | None = Field(None, description="Exports a high quality mesh.")
    # TODO implementation
    # bounds_file: str | None = Field(
    #     None,
    #     description="A file that defines the bounding box or ROI that will be voxelized and meshed. This option is used to select a specifc region of interest from the space to voxelize.",
    # )
    edge_gap: float | None = Field(
        None, description="Some little extra space to avoid edges intersection. Default 0.05."
    )
    resolution: int | None = Field(
        None,
        description="The base resolution of the volume. Default 512. This resolution is set to the larget dimension of the bounding box of the input dataset, and the resolution of the other dimensions are computed accordingly.",
    )
    scaled_resolution: bool | None = Field(
        None, description="Sets the resolution of the volume based on the mesh dimensions."
    )
    voxels_per_micron: float | None = Field(
        None,
        description="Number of voxels per micron. If this flag is set, then resolution will be ignored.",
    )
    volume_type: str | None = Field(
        None,
        description="Specify a volume format to perform the voxelization: [bit, byte, voxel, sparse, roaring]. By default, it is a bit volume to reduce the memory foot print.",
    )
    ignore_solid: bool | None = Field(
        None,
        description="Ignore solid voxelization and use only surface voxelization. Note that solid voxelization is used to fill the interior of the volume shell, therefore the surface shell will be only created and the interior will not be filled. This will result in wrong remeshing and skeletonization results.",
    )
    voxelization_axis: str | None = Field(
        None,
        description="The axis where the solid voxelization operation will be performed. Use one of the following options [x, y, z, and-xyz, or-xyz]. If you use x or y or z the voxelization will happen along a single axis, otherwise, using xyz will perform the solid voxelization along the three main axes of the volume to avoid filling any loops in the morphology. By default, the Z-axis solid voxelization with xyz is applied if the --solid flag is set.",
    )
    conservative: bool | None = Field(
        None,
        description="Use conservative rasterizationto to ensure that all the voxels that are touched by triangles are rasterized.",
    )
    project_xy: bool | None = Field(
        None, description="Project the volume along the Z-axis into a gray-scale image."
    )
    project_xz: bool | None = Field(
        None, description="Project the volume along the Y-axis into a gray-scale image."
    )
    project_zy: bool | None = Field(
        None, description="Project the volume along the X-axis into a gray-scale image."
    )
    project_color_coded: bool | None = Field(
        None, description="Generate color-coded projections of the volume to help debugging it."
    )
    export_stack_xy: bool | None = Field(
        None, description="Generate an image stack along the Z-axis of the volume."
    )
    export_stack_xz: bool | None = Field(
        None, description="Generate an image stack along the Y-axis of the volume."
    )
    export_stack_zy: bool | None = Field(
        None, description="Generate an image stack along the X-axis of the volume."
    )
    export_bit_volume: bool | None = Field(
        None,
        description="Export an Ultraliser-specific bit volume, where each voxel is stored in 1 bit. The header and data are stored in a single file with the extention .vol.",
    )
    export_unsigned_volume: bool | None = Field(
        None,
        description="Export an Ultraliser-specific unsigned volume, where each voxel is stored either in 1, 2, 3 or 4 bytes depending on the type of the volume. The data and header are stored in a single file with the extention .vol.",
    )
    export_float_volume: bool | None = Field(
        None,
        description="Export an Ultraliser-specific float volume, where each voxel is stored in float. The data and header are stored in a single file with the extention .vol.",
    )
    export_raw_volume: bool | None = Field(
        None,
        description="Export a raw volume, where each voxel is stored in 1, 2, 3 or 4 bytes depending on the volume type. The resulting files are: .img file (contains data) and .hdr file (meta-data)",
    )
    export_nrrd_volume: bool | None = Field(
        None,
        description="Export a .nrrd volume that is compatible with VTK and can be loaded with Paraview for visualization purposes. The resulting file contains the header and the data.",
    )
    export_volume_point_cloud_mesh: bool | None = Field(
        None,
        description="Export a point cloud mesh that represents the volume where each voxel will be a point.",
    )
    export_volume_mesh: bool | None = Field(
        None,
        description="Export a mesh that represents the volume where each voxel will be a cube.",
    )
    export_volume_bounding_box_mesh: bool | None = Field(
        None,
        description="Export a mesh that represents the bounding box of the volume. This mesh is primarily used for debugging purposes.",
    )
    export_volume_grid_mesh: bool | None = Field(
        None,
        description="Export a mesh that represents the volumetric grid used to voxelize the mesh. This mesh is primarily used for debugging purposes.",
    )
    export_obj_mesh: bool | None = Field(
        None, description="Export the resulting mesh(es) to Wavefront format (.obj)."
    )
    export_ply_mesh: bool | None = Field(
        None, description="Export the resulting mesh(es) to the Stanford triangle format (.ply)."
    )
    export_off_mesh: bool | None = Field(
        None, description="Export the resulting mesh(es) to the object file format (.off)."
    )
    export_stl_mesh: bool | None = Field(
        None,
        description="Export the resulting mesh(es) to the stereolithography CAD format (.stl).",
    )
    isosurface_technique: str | None = Field(
        None,
        description="Specify a technique to extract the isosurface from the volume: [mc, dmc]. By default, it is dmc (Dual Marching Cubes)",
    )
    preserve_partitions: bool | None = Field(
        None,
        description="Keeps all the partitions of the mesh if the input mesh contains more than one.",
    )
    optimize_mesh: bool | None = Field(
        None,
        description="Optimize the reconstructed mesh using the default optimization strategy.",
    )
    adaptive_optimization: bool | None = Field(
        None,
        description="Optimize the reconstructed mesh using the adaptive optimization strategy.",
    )
    optimization_iterations: int | None = Field(
        None,
        description="Number of iterations to optimize the resulting mesh. Default value 1. If this value is set to 0, the optimization process will be ignored.",
    )
    smooth_iterations: int | None = Field(
        None, description="Number of iterations to smooth the reconstructed mesh, Default 5."
    )
    flat_factor: float | None = Field(
        None, description="A factor that is used for the coarseFlat function. Default 0.05."
    )
    dense_factor: float | None = Field(
        None, description="A factor that is used for the coarseDense function. Default 5.0."
    )
    min_dihedral_angle: float | None = Field(
        None, description="The required minimum dihedral angle. Default 0.1"
    )
    laplacian_iterations: int | None = Field(
        None,
        description="Number of iterations to smooth the reconstructed mesh with Laplacian filter. Default 10.",
    )
    x_scale: float | None = Field(
        None, description="Scaling factor for the mesh along the X-axis, Default 1.0."
    )
    y_scale: float | None = Field(
        None, description="Scaling factor for the mesh along the Y-axis. Default 1.0."
    )
    z_scale: float | None = Field(
        None, description="Scaling factor for the mesh along the Z-axis. Default 1.0."
    )
    ignore_marching_cubes_mesh: bool | None = Field(
        None,
        description="If this flag is set, the mesh reconstructed with the marching cubes algorithm will not be written to disk.",
    )
    ignore_laplacian_mesh: bool | None = Field(
        None,
        description="If this flag is set, the mesh resulting from the application of the Laplacian operator will be ignored and will not be written to disk.",
    )
    ignore_optimized_mesh: bool | None = Field(
        None, description="If this flag is set, the optimized mesh will not be written to disk."
    )
    ignore_watertight_mesh: bool | None = Field(
        None, description="If this flag is set, the watertight mesh will not be written to disk."
    )
    # stats: bool = Field(
    #     None, description="Write the statistics of the resulting meshes/volumes/morphologies."
    # )
    dists: bool | None = Field(
        None, description="Write the distributions of the resulting meshes/volumes/morphologies."
    )
    # skeletonization_stats: bool = Field(
    #     False, description="Write the statistics of the skeletonization process."
    # )
    use_acceleration: bool = Field(
        False,
        description="Use acceleration data structures to improve the performance of the skeletonization operation. Note that this option requires more memory.",
    )


class SkeletonizationJobOutput(BaseModel):
    reconstruction_morphology: ReconstructionMorphology
