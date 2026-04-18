"""
Thumbnail generator.
Renders a PNG thumbnail from an STL/OBJ/3MF file using trimesh's
offscreen renderer (no GPU needed — uses software rasterisation).
"""

from __future__ import annotations

import io
from pathlib import Path


def generate_thumbnail(
    mesh_path: Path,
    size: tuple[int, int] = (512, 512),
    background: tuple[int, int, int] = (245, 245, 245),
) -> bytes | None:
    """
    Render a thumbnail PNG from a mesh file.

    Args:
        mesh_path: Path to STL/3MF/OBJ file.
        size: Output image dimensions in pixels.
        background: RGB background colour.

    Returns:
        PNG bytes, or None if rendering fails.
    """
    try:
        import numpy as np
        import trimesh
        from PIL import Image
    except ImportError:
        return None

    try:
        mesh = trimesh.load(str(mesh_path), force="mesh")

        if len(mesh.faces) == 0:
            return _blank_thumbnail(size, background)

        # Centre and normalise the mesh
        mesh.apply_translation(-mesh.centroid)
        scale = 1.0 / mesh.scale if mesh.scale > 0 else 1.0
        mesh.apply_scale(scale)

        # Try scene-based rendering (works without GPU via software)
        scene = mesh.scene()

        # Isometric-ish camera angle
        scene.set_camera(angles=[0.4, 0.0, 0.8], distance=2.0, center=[0, 0, 0])

        try:
            png_bytes = scene.save_image(resolution=size, visible=False)
            if png_bytes:
                return png_bytes
        except Exception:
            pass

        # Fallback: generate a simple projection image with PIL
        return _projection_thumbnail(mesh, size, background)

    except Exception:
        return _blank_thumbnail(size, background)


def _projection_thumbnail(mesh, size: tuple[int, int], bg: tuple[int, int, int]) -> bytes:
    """
    Simple orthographic projection fallback.
    Projects mesh vertices onto a 2D plane and draws filled triangles.
    """
    try:
        import numpy as np
        from PIL import Image, ImageDraw

        img = Image.new("RGB", size, bg)
        draw = ImageDraw.Draw(img)

        verts = mesh.vertices[:, :2]   # XY projection
        if verts.shape[0] == 0:
            return _blank_thumbnail(size, bg)

        # Normalise to image coords
        v_min, v_max = verts.min(axis=0), verts.max(axis=0)
        span = v_max - v_min
        span[span == 0] = 1.0
        margin = 40
        scale = (min(size) - 2 * margin) / span.max()

        def to_img(v):
            x = (v[:, 0] - v_min[0]) * scale + margin
            y = size[1] - ((v[:, 1] - v_min[1]) * scale + margin)
            return np.stack([x, y], axis=1)

        img_verts = to_img(verts)

        for face in mesh.faces[:5000]:   # cap for performance
            pts = [(float(img_verts[i, 0]), float(img_verts[i, 1])) for i in face]
            draw.polygon(pts, fill=(100, 180, 220), outline=(60, 100, 140))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return _blank_thumbnail(size, bg)


def _blank_thumbnail(size: tuple[int, int], bg: tuple[int, int, int]) -> bytes:
    """Return a plain-coloured PNG when all else fails."""
    from PIL import Image
    img = Image.new("RGB", size, bg)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
