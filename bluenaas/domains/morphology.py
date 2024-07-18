from typing import List

from pydantic import BaseModel


class LocationData(BaseModel):
    index: int
    nseg: int
    xstart: List[float]
    xend: List[float]
    xcenter: List[float]
    xdirection: List[float]
    ystart: List[float]
    yend: List[float]
    ycenter: List[float]
    ydirection: List[float]
    zstart: List[float]
    zend: List[float]
    zcenter: List[float]
    zdirection: List[float]
    segx: List[float]
    diam: List[float]
    length: List[float]
    distance: List[float]
