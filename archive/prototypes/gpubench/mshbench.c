/*
 * mshbench: small GLES 3 benchmark that builds unchanged for the host (Linux, Mesa) and the Android guest (NDK),
 * so a VM's GPU path can be compared with the same GPU used natively. Offscreen (FBO in a pbuffer context).
 *
 *   fill     fullscreen quads with an ALU-heavy fragment shader into a 1080x2520 target   -> Gpixel/s (GPU bound)
 *   draws    many small draw calls with a uniform change each                             -> draws/s (CPU+submit)
 *   upload   glTexSubImage2D of a 1080x2520 RGBA frame                                    -> MB/s
 *   readback glReadPixels of a 1080x2520 RGBA frame                                       -> MB/s
 *   frame    one small draw + glFinish per frame                                          -> round-trip us
 *
 * host:  cc -O2 -o mshbench mshbench.c -lEGL -lGLESv2        (run with EGL_PLATFORM=surfaceless)
 * guest: $NDK/aarch64-linux-android35-clang -O2 -o mshbench mshbench.c -lEGL -lGLESv3
 */
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define W 1080
#define H 2520

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec * 1e-9;
}

static GLuint shader(GLenum type, const char *src)
{
	GLuint s = glCreateShader(type);
	glShaderSource(s, 1, &src, NULL);
	glCompileShader(s);
	GLint ok;
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		char log[1024];
		glGetShaderInfoLog(s, sizeof(log), NULL, log);
		fprintf(stderr, "shader: %s\n", log);
		exit(1);
	}
	return s;
}

static GLuint program(const char *vs, const char *fs)
{
	GLuint p = glCreateProgram();
	glAttachShader(p, shader(GL_VERTEX_SHADER, vs));
	glAttachShader(p, shader(GL_FRAGMENT_SHADER, fs));
	glBindAttribLocation(p, 0, "pos");
	glLinkProgram(p);
	return p;
}

static const char *VS =
	"#version 300 es\n"
	"in vec2 pos; uniform vec4 xf; out vec2 uv;\n"
	"void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos * xf.zw + xf.xy, 0.0, 1.0); }\n";
static const char *FS_HEAVY =
	"#version 300 es\n"
	"precision highp float; in vec2 uv; uniform float t; out vec4 o;\n"
	"void main() { vec3 c = vec3(uv, t);\n"
	"  for (int i = 0; i < 16; i++) c = fract(sin(c * 12.9898 + c.yzx * 78.233) * 43758.5453);\n"
	"  o = vec4(c, 1.0); }\n";
static const char *FS_FLAT =
	"#version 300 es\n"
	"precision mediump float; uniform float t; out vec4 o;\n"
	"void main() { o = vec4(t, 0.5, 0.25, 1.0); }\n";

int main(int argc, char **argv)
{
	double secs = argc > 1 ? atof(argv[1]) : 3.0;	/* per test */
	EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
	if (!eglInitialize(d, NULL, NULL)) { fprintf(stderr, "eglInitialize failed\n"); return 1; }
	EGLint ca[] = { EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
		EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE };
	EGLConfig cfg; EGLint n;
	if (!eglChooseConfig(d, ca, &cfg, 1, &n) || n < 1) { fprintf(stderr, "no config\n"); return 1; }
	EGLint sa[] = { EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE };
	EGLSurface s = eglCreatePbufferSurface(d, cfg, sa);
	eglBindAPI(EGL_OPENGL_ES_API);
	EGLint xa[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
	EGLContext c = eglCreateContext(d, cfg, EGL_NO_CONTEXT, xa);
	if (!eglMakeCurrent(d, s, s, c)) { fprintf(stderr, "eglMakeCurrent failed\n"); return 1; }
	printf("renderer: %s | %s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));

	GLuint tex, fbo;
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA8, W, H);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
	glViewport(0, 0, W, H);

	static const float quad[] = { -1, -1, 1, -1, -1, 1, 1, 1 };
	GLuint vbo;
	glGenBuffers(1, &vbo);
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
	glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
	glEnableVertexAttribArray(0);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

	GLuint heavy = program(VS, FS_HEAVY), flat = program(VS, FS_FLAT);
	double t0, dt; long i;

	/* fill: 4 fullscreen heavy quads per frame */
	glUseProgram(heavy);
	glUniform4f(glGetUniformLocation(heavy, "xf"), 0, 0, 1, 1);
	GLint ut = glGetUniformLocation(heavy, "t");
	glFinish();
	for (i = 0, t0 = now(); (dt = now() - t0) < secs; i++) {
		for (int q = 0; q < 4; q++) {
			glUniform1f(ut, (float)(i * 4 + q) * 0.001f);
			glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
		}
		glFinish();
	}
	printf("fill:     %7.2f Gpixel/s  (%ld frames of 4 x %dx%d, 16-iteration shader)\n",
	       i * 4.0 * W * H / dt / 1e9, i, W, H);

	/* draws: 2000 small quads per batch, uniform change each */
	glUseProgram(flat);
	GLint fxf = glGetUniformLocation(flat, "xf"), ft = glGetUniformLocation(flat, "t");
	glFinish();
	long draws = 0;
	for (t0 = now(); (dt = now() - t0) < secs;) {
		for (int k = 0; k < 2000; k++, draws++) {
			glUniform4f(fxf, (k % 40) * 0.05f - 1.0f, (k / 40) * 0.04f - 1.0f, 0.02f, 0.02f);
			glUniform1f(ft, k * 0.0005f);
			glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
		}
		glFinish();
	}
	printf("draws:    %7.0f k draws/s\n", draws / dt / 1e3);

	/* upload */
	unsigned char *pix = malloc((size_t)W * H * 4);
	memset(pix, 0x5a, (size_t)W * H * 4);
	GLuint up;
	glGenTextures(1, &up);
	glBindTexture(GL_TEXTURE_2D, up);
	glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA8, W, H);
	glFinish();
	for (i = 0, t0 = now(); (dt = now() - t0) < secs; i++) {
		glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, pix);
		glFinish();
	}
	printf("upload:   %7.0f MB/s\n", i * (double)W * H * 4 / dt / 1e6);

	/* readback */
	for (i = 0, t0 = now(); (dt = now() - t0) < secs; i++)
		glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, pix);
	printf("readback: %7.0f MB/s\n", i * (double)W * H * 4 / dt / 1e6);

	/* frame round trip: one tiny draw + glFinish */
	glUseProgram(flat);
	glUniform4f(fxf, 0, 0, 0.01f, 0.01f);
	glFinish();
	for (i = 0, t0 = now(); (dt = now() - t0) < secs; i++) {
		glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
		glFinish();
	}
	printf("frame:    %7.1f us per draw+finish round trip\n", dt / i * 1e6);
	return 0;
}
