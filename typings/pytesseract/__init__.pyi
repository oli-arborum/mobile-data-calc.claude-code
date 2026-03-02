from typing import TypedDict

from PIL import Image

class Output:
    BYTES: str
    DATAFRAME: str
    DICT: str
    STRING: str

class TesseractData(TypedDict):
    level: list[int]
    page_num: list[int]
    block_num: list[int]
    par_num: list[int]
    line_num: list[int]
    word_num: list[int]
    left: list[int]
    top: list[int]
    width: list[int]
    height: list[int]
    conf: list[int]
    text: list[str]

def image_to_string(
    image: Image.Image,
    lang: str | None = None,
    config: str = "",
    nice: int = 0,
    output_type: str = Output.STRING,
    timeout: int = 0,
) -> str: ...

def image_to_data(
    image: Image.Image,
    lang: str | None = None,
    config: str = "",
    nice: int = 0,
    output_type: str = Output.DICT,
    timeout: int = 0,
) -> TesseractData: ...
