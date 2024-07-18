"""Model"""

from loguru import logger as L

from bluenaas.core.cell import HocCell
from bluenaas.external.nexus.nexus import Nexus


class Model:
    def __init__(self, *, model_id: str, token: str):
        self.model_id: str = model_id
        self.token: str = token
        self.CELL: HocCell = None
        self.THRESHOLD_CURRENT: int = 1

    def build_model(self):
        """Prepare model."""
        if self.model_id is None:
            raise Exception("Missing model _self url")

        nexus_helper = Nexus({"token": self.token, "model_self_url": self.model_id})
        model_uuid = nexus_helper.get_model_uuid()
        nexus_helper.download_model()
        [holding_current, threshold_current] = nexus_helper.get_currents()
        self.THRESHOLD_CURRENT = threshold_current

        if self.CELL is None:
            L.debug(
                f"loading model {model_uuid}",
            )
            L.debug(f"threshold_current {threshold_current}")
            L.debug(f"holding_current {holding_current}")
            self.CELL = HocCell(model_uuid, threshold_current, holding_current)

        elif self.CELL.model_uuid != model_uuid:
            L.debug(
                "Trying to load different model",
                f"current: {self.CELL.model_uuid}, new: {model_uuid}, discarding the pod",
            )
            raise Exception("Different model")
        return True
