import os
from pathlib import Path

from app.core.types import FileObj
from app.utils.util import get_model_path

RWX_TO_ALL = 0o777


def opener(path, flags):
    return os.open(path, flags, RWX_TO_ALL)


class Service:
    model_uuid: str

    def create_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", opener=opener) as f:
            f.write(content)

    def copy_file_content(self, source_file: Path, target_file: Path):
        with open(source_file, "r") as src, open(
            target_file, "w", opener=opener
        ) as dst:
            dst.write(src.read())

    def create_model_folder(
        self, hoc_file: str, morphology_obj: FileObj, mechanisms: list[FileObj]
    ):
        output_dir = get_model_path(self.model_uuid)

        self.create_file(output_dir / "cell.hoc", hoc_file)

        morph_name = morphology_obj["name"]
        self.create_file(
            output_dir / "morphology" / morph_name, morphology_obj["content"]
        )

        for mechanism in mechanisms:
            mech_name = mechanism["name"]
            self.create_file(
                output_dir / "mechanisms" / mech_name, mechanism["content"]
            )

        self.copy_file_content(
            Path("/app/app/config/VecStim.mod"),
            output_dir / "mechanisms" / "VecStim.mod",
        )
        self.copy_file_content(
            Path("/app/app/config/ProbGABAAB_EMS.mod"),
            output_dir / "mechanisms" / "ProbGABAAB_EMS.mod",
        )
        self.copy_file_content(
            Path("/app/app/config/ProbAMPANMDA_EMS.mod"),
            output_dir / "mechanisms" / "ProbAMPANMDA_EMS.mod",
        )
