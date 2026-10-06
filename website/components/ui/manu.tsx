"use client";

import { useEffect, useRef } from "react";

const VERT = `
attribute vec2 a_position;
void main() { gl_Position = vec4(a_position, 0.0, 1.0); }
`;

// Deliberately conservative WebGL 1 shader: no dynamic indexing, texture
// lookups, derivative extensions, or precision-sensitive noise loops.
const FRAG = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 u_resolution;
uniform float u_time;

float field(vec2 p, vec2 c, float r) {
  vec2 d = p - c;
  return exp(-dot(d, d) / r);
}

void main() {
  vec2 uv = gl_FragCoord.xy / max(u_resolution.xy, vec2(1.0));
  vec2 p = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / max(min(u_resolution.x, u_resolution.y), 1.0);
  float t = u_time;

  vec2 c1 = vec2(-0.42 + 0.34*sin(t*0.31), -0.24 + 0.24*cos(t*0.23));
  vec2 c2 = vec2( 0.46 + 0.30*cos(t*0.21), -0.08 + 0.30*sin(t*0.27));
  vec2 c3 = vec2(-0.02 + 0.42*sin(t*0.17+1.8), 0.48 + 0.20*cos(t*0.19));
  vec2 c4 = vec2( 0.18 + 0.32*cos(t*0.14+2.1), 0.12 + 0.28*sin(t*0.16+1.1));

  float f1 = field(p, c1, 0.24);
  float f2 = field(p, c2, 0.28);
  float f3 = field(p, c3, 0.30);
  float f4 = field(p, c4, 0.18);

  vec3 base = vec3(0.035, 0.012, 0.070);
  vec3 violet = vec3(0.36, 0.08, 0.78);
  vec3 blueViolet = vec3(0.16, 0.20, 0.62);
  vec3 lavender = vec3(0.46, 0.28, 0.82);
  vec3 warm = vec3(0.34, 0.10, 0.38);

  vec3 col = base;
  col += violet * f1 * 0.95;
  col += blueViolet * f2 * 0.82;
  col += lavender * f3 * 0.70;
  col += warm * f4 * 0.24;

  float wave = 0.5 + 0.5*sin((p.x*3.4 + p.y*2.2) + t*0.28);
  col += vec3(0.09, 0.035, 0.16) * wave * 0.18;
  float vignette = smoothstep(0.95, 0.18, length(uv - 0.5));
  col *= 0.66 + vignette * 0.44;
  float grain = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5;
  col += grain * 0.016;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
`;

export function ShaderBackground({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", {
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
    if (!gl) {
      canvas.style.background = "radial-gradient(circle at 25% 25%, #6422b7, transparent 42%), radial-gradient(circle at 78% 35%, #293b9d, transparent 45%), #12071f";
      return;
    }

    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        const message = gl.getShaderInfoLog(shader);
        if (message) console.warn("Shader compile failed:", message);
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vertex = compile(gl.VERTEX_SHADER, VERT);
    const fragment = compile(gl.FRAGMENT_SHADER, FRAG);
    if (!vertex || !fragment) {
      canvas.style.background = "radial-gradient(circle at 25% 25%, #6422b7, transparent 42%), radial-gradient(circle at 78% 35%, #293b9d, transparent 45%), #12071f";
      return;
    }

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const message = gl.getProgramInfoLog(program);
      if (message) console.warn("Shader link failed:", message);
      gl.deleteProgram(program);
      return;
    }
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const resolution = gl.getUniformLocation(program, "u_resolution");
    const time = gl.getUniformLocation(program, "u_time");

    let frame = 0;
    let active = true;
    const started = performance.now();
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = Math.max(1, Math.round(rect.width * dpr));
      const height = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        gl.viewport(0, 0, width, height);
      }
    };
    const render = (now: number) => {
      frame = 0;
      if (!active || gl.isContextLost()) return;
      resize();
      gl.uniform2f(resolution, canvas.width, canvas.height);
      gl.uniform1f(time, ((now - started) / 1000) * 6);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      frame = requestAnimationFrame(render);
    };
    const observer = new IntersectionObserver(([entry]) => {
      active = entry?.isIntersecting ?? true;
      if (active && !frame) frame = requestAnimationFrame(render);
      if (!active && frame) { cancelAnimationFrame(frame); frame = 0; }
    }, { rootMargin: "120px" });
    observer.observe(canvas);
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    frame = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      resizeObserver.disconnect();
      if (buffer) gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} style={{ display: "block", width: "100%", height: "100%" }} />;
}
