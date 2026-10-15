"""Built-in image providers (ids match upstream's ``ImageProvider`` enum).

The registry is the seam: ``services/image_generation_service.py`` still holds the
request code per provider; the customisation workstream moves each into
``generate(prompt, creds) -> path | url`` here.
"""

from chatppt.providers.base import ImageProviderSpec
from chatppt.providers.registry import register_image

register_image(ImageProviderSpec("pexels", "Pexels (stock photos)", "stock"))
register_image(ImageProviderSpec("pixabay", "Pixabay (stock photos)", "stock"))
register_image(ImageProviderSpec("gemini_flash", "Gemini Flash image", "generative", default_model="gemini-2.5-flash-image"))
register_image(ImageProviderSpec("nanobanana_pro", "Gemini 3 Pro image", "generative", default_model="gemini-3-pro-image-preview"))
register_image(ImageProviderSpec("dall-e-3", "OpenAI DALL·E 3", "generative", default_model="dall-e-3"))
register_image(ImageProviderSpec("gpt-image-1.5", "OpenAI gpt-image-1.5", "generative", default_model="gpt-image-1.5"))
register_image(ImageProviderSpec("comfyui", "ComfyUI", "generative", needs=("base_url", "workflow")))
register_image(ImageProviderSpec("open_webui", "Open WebUI", "generative", needs=("base_url", "api_key")))
register_image(ImageProviderSpec("openai_compatible", "OpenAI-compatible images endpoint", "generative", needs=("base_url", "api_key", "model")))
