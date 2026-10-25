"""Shared orientation, color-profile and transparency normalization."""

import io

from PIL import Image, ImageCms, ImageOps

PREPROCESSING = "pillow-orient-srgb-1280-q82-v2"


def normalized(image):
    image = ImageOps.exif_transpose(image)
    profile = image.info.get("icc_profile")
    alpha = image.convert("RGBA").getchannel("A") if image.mode in ("RGBA", "LA", "P") else None
    if profile:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            image = ImageCms.profileToProfile(
                image, source, ImageCms.createProfile("sRGB"), outputMode="RGB"
            )
        except (ImageCms.PyCMSError, OSError, ValueError) as error:
            raise ValueError("invalid or unsupported embedded color profile") from error
    else:
        image = image.convert("RGB")
    if alpha is not None:
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=alpha)
        image = background
    image.info.clear()
    return image
