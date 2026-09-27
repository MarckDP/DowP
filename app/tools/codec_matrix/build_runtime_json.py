# tools/codec_matrix/build_runtime_json.py
"""
Convierte una corrida cruda de run_matrix.py (runs/<version>.json) en el JSON final,
pensado para que la app lo consulte en runtime: claves = codec_id de ffmpeg (h264, hevc,
aac...) en vez de nombres de Wikipedia, y el motivo de fallo es el error real de ffmpeg,
no una nota editorializada.

No tiene relacion con codec_container_compatibility.json (el de Wikipedia) - son fuentes
independientes a proposito. Este es el que deberia usar el "colchon" para bloquear o
advertir; el de Wikipedia queda como referencia historica aparte.

Uso:
    python tools/codec_matrix/build_runtime_json.py
    python tools/codec_matrix/build_runtime_json.py --run runs/8.0.1-full_build-www.gyan.dev.json --out ../../src/assets/data/ffmpeg_codec_matrix.json
"""
import argparse
import json
import os

HERE = os.path.dirname(__file__)
DEFAULT_RUN = os.path.join(HERE, "runs", "latest.json")
DEFAULT_OUT = os.path.join(HERE, "..", "..", "src", "assets", "data", "ffmpeg_codec_matrix.json")


def build(run_path, out_path):
    with open(run_path, "r", encoding="utf-8") as f:
        run = json.load(f)

    codecs = {}
    for kind in ("video_codecs", "audio_codecs"):
        for name, entry in run["results"][kind].items():
            codec_id = entry.get("codec_id", name)
            kind_short = "video" if kind == "video_codecs" else "audio"

            if not entry.get("testable"):
                codecs[codec_id] = {
                    "kind": kind_short,
                    "display_name": entry.get("display_name", codec_id),
                    "wikipedia_name": entry.get("wiki"),
                    "encoder": entry.get("encoder"),
                    "verified": False,
                    "skip_reason": entry.get("skip_reason"),
                    "containers": None,
                }
                continue

            containers = {}
            for cont_id, c in entry["containers"].items():
                cont_out = {
                    "supported": c["result"] == "pass",
                    "ffmpeg_error": c.get("error"),
                }
                if "channels" in c:
                    cont_out["channels"] = {
                        ch: {"supported": c_res["result"] == "pass", "ffmpeg_error": c_res.get("error")}
                        for ch, c_res in c["channels"].items()
                    }
                containers[cont_id] = cont_out

            codecs[codec_id] = {
                "kind": kind_short,
                "display_name": entry.get("display_name", codec_id),
                "wikipedia_name": entry.get("wiki"),
                "encoder": entry.get("encoder"),
                "verified": True,
                "skip_reason": None,
                "containers": containers,
            }
            if "channels" in entry:
                channels_data = {}
                for ch, c_res in entry["channels"].items():
                    channels_data[ch] = {
                        "supported": c_res["result"] == "pass",
                        "ffmpeg_error": c_res.get("error"),
                    }
                codecs[codec_id]["channels"] = channels_data

            if entry.get("note"):
                codecs[codec_id]["note"] = entry["note"]

            if kind_short == "video" and entry.get("dimension_alignment"):
                codecs[codec_id]["dimension_alignment"] = entry["dimension_alignment"]

            # Transparencia (ver run_matrix.py::probe_alpha). "encode" es exactamente lo que
            # se uso para verificarlo (pix_fmt + args extra) y "decoder" con que hay que
            # LEER el archivo para que el alfa aparezca (VP8/VP9) -- la app debe repetir
            # ambos tal cual. Por contenedor: full | 1bit | lost | partial | write_error |
            # unreadable; solo "full" y "1bit" conservan transparencia.
            # Combinaciones que se ESCRIBEN pero ffmpeg no puede volver a leer, ni siquiera
            # sin alfa (detectado por la prueba de alfa, ver run_matrix.py::_opaque_readable):
            # el mux base las daba por buenas porque solo mira que el archivo se escriba.
            # Se marcan no soportadas, asi la app deja de ofrecer un archivo inservible.
            if kind_short == "video" and entry.get("alpha"):
                for cont_id, r in (entry["alpha"].get("containers") or {}).items():
                    if r.get("result") == "unreadable" and r.get("opaque_readable") is False                             and cont_id in containers and containers[cont_id]["supported"]:
                        containers[cont_id]["supported"] = False
                        containers[cont_id]["ffmpeg_error"] = (
                            "Se escribe, pero ffmpeg no puede volver a leer el archivo "
                            "(verificado releyendo el resultado).")
                        containers[cont_id]["unreadable"] = True

            if kind_short == "video" and entry.get("alpha"):
                a = entry["alpha"]
                codecs[codec_id]["alpha"] = {
                    "encode": {"pix_fmt": a.get("pix_fmt"), "extra_args": a.get("extra") or []},
                    "decoder": a.get("decoder"),
                    "containers": {
                        cont_id: {k: v for k, v in r.items()
                                  if k in ("result", "error", "alpha_error", "alpha_read", "opaque_readable")}
                        for cont_id, r in a.get("containers", {}).items()
                    },
                }

    container_streams = {}
    for cont_id, entry in run.get("container_streams", {}).items():
        container_streams[cont_id] = {
            "audio_only_multi": {
                codec_name: {"supported": r["result"] == "pass", "ffmpeg_error": r.get("error")}
                for codec_name, r in entry.get("audio_only_multi", {}).items()
            },
            "video_audio_multi": {
                pair_name: {"supported": r["result"] == "pass", "ffmpeg_error": r.get("error")}
                for pair_name, r in entry.get("video_audio_multi", {}).items()
            },
        }

    output = {
        # 2.1: + "alpha" por codec de video (transparencia por contenedor).
        "schema_version": "2.1",
        "source": "empirico: mux real contra el ffmpeg empaquetado, ver tools/codec_matrix/",
        "ffmpeg_version": run["meta"]["ffmpeg_version"],
        "ffmpeg_version_full": run["meta"]["ffmpeg_version_full"],
        "generated_at": run["meta"]["generated_at"],
        "containers": list(next(iter(codecs.values()))["containers"].keys()) if codecs else [],
        "codecs": codecs,
        # Multipista por contenedor (ver tools/codec_matrix/run_matrix.py::probe_container_streams):
        # eje INDEPENDIENTE de "codecs" de arriba - ahi se responde "¿este codec entra en este
        # contenedor?" (1 sola pista); aca "¿este contenedor acepta 2 streams simultaneos de
        # ESTE codec?" (audio_only_multi), o "¿acepta video + 2 audios de ESTE par de codecs?"
        # (video_audio_multi, clave "video_codec+audio_codec"). Un contenedor/codec ausente en
        # estos dicts significa "no aplica" (ej. audio_only_multi en GIF: no acepta audio en
        # absoluto), no "no soportado" - para eso hay que fijarse si la clave existe.
        "container_streams": container_streams,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Escrito: {out_path}")
    verified = sum(1 for c in codecs.values() if c["verified"])
    print(f"Codecs verificados: {verified}/{len(codecs)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.run, args.out)
