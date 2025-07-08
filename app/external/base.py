from pathlib import Path
from uuid import UUID

from app.core.types import FileObj
from app.infrastructure.storage import (
    copy_file_content,
    create_file,
    get_single_cell_location,
)


class Service:
    model_id: UUID

    def create_model_folder(
        self, hoc_file: bytes, morphology_obj: FileObj, mechanisms: list[FileObj]
    ):
        output_dir = get_single_cell_location(self.model_id)

        create_file(output_dir / "cell.hoc", hoc_file)

        morph_name = morphology_obj["name"]
        create_file(output_dir / "morphology" / morph_name, morphology_obj["content"])

        for mechanism in mechanisms:
            mech_name = mechanism["name"]
            create_file(output_dir / "mechanisms" / mech_name, mechanism["content"])

        copy_file_content(
            Path("/app/app/config/VecStim.mod"),
            output_dir / "mechanisms" / "VecStim.mod",
        )
        copy_file_content(
            Path("/app/app/config/ProbGABAAB_EMS.mod"),
            output_dir / "mechanisms" / "ProbGABAAB_EMS.mod",
        )
        copy_file_content(
            Path("/app/app/config/ProbAMPANMDA_EMS.mod"),
            output_dir / "mechanisms" / "ProbAMPANMDA_EMS.mod",
        )
