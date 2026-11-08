"""Interactive inspection from the center of a cube texture."""
from math import asin, atan2, cos, degrees, radians, sin, tan

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import (
    QOpenGLPixelTransferOptions, QOpenGLShader, QOpenGLShaderProgram,
    QOpenGLTexture, QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from shiboken6 import VoidPtr

from .messages import Message, msg
from .topology import CUBE_AXES

VERTEX = """
#version 330 core
out vec2 ndc;
void main() {
    ndc = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2) * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
}
"""

FRAGMENT = """
#version 330 core
in vec2 ndc;
out vec4 pixel;
uniform samplerCube sky;
uniform vec3 forward, right, up;
void main() {
    pixel = vec4(texture(sky, forward + ndc.x * right + ndc.y * up).rgb, 1.0);
}
"""


def camera_axes(yaw, pitch):
    # COD world up is +Z. At zero yaw the camera looks along -Y.
    yaw, pitch = radians(yaw), radians(pitch)
    sy, cy = sin(yaw), cos(yaw)
    sp, cp = sin(pitch), cos(pitch)
    return (sy * cp, -cy * cp, sp), (cy, sy, 0.), (-sy * sp, cy * sp, cp)


class CubePreview(QOpenGLWidget):
    camera_changed = Signal(object)
    failed = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.camera = [0., 0., 75.]
        self.drag = None
        self.faces = None
        self.texture = None
        self.program = None
        self.vao = None
        self.init_error = None
        self.generation = 0

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.check_context)

    def check_context(self):
        if not self.isVisible():
            return
        if not self.isValid():
            self.report_failure(msg('error.gl_context'))
        elif self.init_error is not None:
            self.report_failure(self.init_error)

    def report_failure(self, error):
        self.failed.emit(self.generation, error)

    def initialization_failed(self, error):
        self.init_error = error
        self.report_failure(error)

    def initializeGL(self):
        self.init_error = None
        self.context().aboutToBeDestroyed.connect(self.release_gl, Qt.ConnectionType.DirectConnection)
        fmt = self.context().format()
        if self.context().isOpenGLES() or (fmt.majorVersion(), fmt.minorVersion()) < (3, 3):
            self.initialization_failed(msg('error.gl_context'))
            return
        program = QOpenGLShaderProgram()
        shader = QOpenGLShader.ShaderTypeBit
        if not (program.addShaderFromSourceCode(shader.Vertex, VERTEX)
                and program.addShaderFromSourceCode(shader.Fragment, FRAGMENT)
                and program.link()):
            self.initialization_failed(Message('error.gl_shader', detail=program.log()))
            return
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            self.initialization_failed(msg('error.gl_context'))
            return
        self.program, self.vao = program, vao

    def release_gl(self):
        self.context().aboutToBeDestroyed.disconnect(self.release_gl)
        self.makeCurrent()
        try:
            self.release_texture()
            if self.vao is not None:
                self.vao.destroy()
                self.vao = None
            self.program = None
        finally:
            self.doneCurrent()

    def release_texture(self):
        if self.texture is not None:
            self.texture.destroy()
            self.texture = None

    def clear_source(self):
        self.generation += 1
        self.faces = None
        self.end_drag()
        if self.texture is not None:
            self.makeCurrent()
            try:
                self.release_texture()
            finally:
                self.doneCurrent()
        self.update()

    def set_faces(self, faces):
        self.clear_source()
        self.faces = faces
        QTimer.singleShot(0, self.check_context)
        self.update()

    def upload(self, gl):
        size = next(iter(self.faces.values()))[0]
        limit = gl.glGetIntegerv(0x851C)  # GL_MAX_CUBE_MAP_TEXTURE_SIZE
        if size > limit:
            self.faces = None
            self.report_failure(msg('error.gl_size', size=size, limit=limit))
            return
        texture = QOpenGLTexture(QOpenGLTexture.Target.TargetCubeMap)
        # Own the texture before allocating/uploading so an exception is cleaned
        # up when the error view retires this source.
        self.texture = texture
        texture.setSize(size, size)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGB8_UNorm)
        texture.setMipLevels(1)
        texture.allocateStorage()
        if not texture.isStorageAllocated():
            self.release_texture()
            self.faces = None
            self.report_failure(msg('error.gl_upload'))
            return
        packing = QOpenGLPixelTransferOptions()
        packing.setAlignment(1)
        for face, (_, data) in self.faces.items():
            normal = CUBE_AXES[face][0]
            axis = next(i for i, value in enumerate(normal) if value)
            target = QOpenGLTexture.CubeMapFace(0x8515 + 2 * axis + int(normal[axis] < 0))
            texture.setData(0, 0, target, QOpenGLTexture.PixelFormat.RGB,
                            QOpenGLTexture.PixelType.UInt8, VoidPtr(data), packing)
        texture.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        error = gl.glGetError()
        if error:
            self.release_texture()
            self.faces = None
            self.report_failure(Message('error.gl_upload', detail=f'OpenGL 0x{error:04X}'))
            return

    def paintGL(self):
        try:
            self.render_frame()
        except Exception as error:
            self.report_failure(Message('error.gl_render', detail=str(error)))

    def render_frame(self):
        gl = self.context().functions()
        background = self.palette().window().color()
        gl.glClearColor(background.redF(), background.greenF(), background.blueF(), 1.)
        gl.glClear(0x4000)  # GL_COLOR_BUFFER_BIT
        if self.program is None or self.faces is None:
            return
        if self.texture is None:
            self.upload(gl)
        if self.texture is None:
            return
        yaw, pitch, fov = self.camera
        forward, right, up = (QVector3D(*axis) for axis in camera_axes(yaw, pitch))
        scale = tan(radians(fov) / 2)
        if not self.program.bind():
            self.report_failure(Message('error.gl_render', detail=self.program.log()))
            return
        gl.glEnable(0x884F)  # GL_TEXTURE_CUBE_MAP_SEAMLESS
        gl.glDisable(0x0B71)  # GL_DEPTH_TEST
        gl.glDisable(0x0B44)  # GL_CULL_FACE
        gl.glDisable(0x0BE2)  # GL_BLEND
        self.program.setUniformValue(self.program.uniformLocation(b'forward'), forward)
        self.program.setUniformValue(self.program.uniformLocation(b'right'), right * (scale * self.width() / max(1, self.height())))
        self.program.setUniformValue(self.program.uniformLocation(b'up'), up * scale)
        self.program.setUniformValue1i(self.program.uniformLocation(b'sky'), 0)
        self.texture.bind(0)
        self.vao.bind()
        try:
            gl.glDrawArrays(0x0004, 0, 3)  # GL_TRIANGLES
            error = gl.glGetError()
            if error:
                self.report_failure(Message('error.gl_render', detail=f'OpenGL 0x{error:04X}'))
        finally:
            self.vao.release()
            self.texture.release(0)
            self.program.release()

    def set_camera(self, values):
        self.camera = list(values)
        self.update()

    def move_camera(self, yaw, pitch, fov):
        self.set_camera((yaw % 360, pitch % 360, max(25., min(110., fov))))
        self.camera_changed.emit(list(self.camera))

    def reset(self):
        self.move_camera(0., 0., 75.)

    def look_at(self, face):
        x, y, z = CUBE_AXES[face][0]
        yaw = degrees(atan2(x, -y)) if x or y else self.camera[0]
        self.move_camera(yaw, degrees(asin(z)), self.camera[2])

    def direction(self):
        forward = camera_axes(*self.camera[:2])[0]
        return max(CUBE_AXES, key=lambda face: sum(a * b for a, b in zip(forward, CUBE_AXES[face][0])))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.drag = event.position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self.drag
            self.drag = event.position()
            yaw, pitch, fov = self.camera
            # Keep the turn speed independent of the panel size and reduce it when zoomed in.
            degrees_per_pixel = 0.14 * fov / 75.
            self.move_camera(yaw + delta.x() * degrees_per_pixel,
                             pitch - delta.y() * degrees_per_pixel, fov)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def end_drag(self):
        self.drag = None
        self.unsetCursor()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.end_drag()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        self.end_drag()
        super().focusOutEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.end_drag()
            self.reset()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        yaw, pitch, fov = self.camera
        self.move_camera(yaw, pitch, fov * 0.9 ** (event.angleDelta().y() / 120))
        event.accept()
