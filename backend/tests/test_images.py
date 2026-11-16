from io import BytesIO

from PIL import Image

from app.core.config import settings
from app.services.images import process_and_store_image


def test_uploaded_image_is_resized_and_normalized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    source = BytesIO()
    Image.new("RGB", (1200, 600), "#171717").save(source, "PNG")

    result = process_and_store_image(source.getvalue())

    assert (result.width, result.height) == (720, 360)
    assert result.filename.endswith(".webp")
    assert result.path.is_file()
