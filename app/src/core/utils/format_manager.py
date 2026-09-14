# src/core/utils/format_manager.py
"""
Motor de inteligencia de medios de DowP 2.0.
Gestiona el parseo de formatos de yt-dlp con un enfoque para editores de video.

Clasificación de 3 tipos:
  - VIDEO       → Combinado (tiene video Y audio)
  - VIDEO_ONLY  → Solo video (necesita audio separado)
  - AUDIO       → Solo audio

Lógica inspirada en el DowP viejo pero simplificada y sin redundancia.
"""
import math
from core.constants import (
    EDITOR_FRIENDLY_CRITERIA, LANG_CODE_MAP,
    VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    LANGUAGE_ORDER, DEFAULT_PRIORITY,
)
from core.logger.logger_manager import logger


class FormatManager:

    # ─── Utilidades ───────────────────────────────────────────

    @staticmethod
    def get_friendly_size(bytes_val):
        if not bytes_val or bytes_val <= 0:
            return ""
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        index = 0
        while bytes_val >= 1024 and index < len(units) - 1:
            bytes_val /= 1024
            index += 1
        return f"{bytes_val:.1f} {units[index]}"

    @staticmethod
    def estimate_size(bitrate_kbps, duration_sec):
        """Calcula peso aproximado: (bitrate * duracion) / 8"""
        if not bitrate_kbps or not duration_sec:
            return 0
        return (bitrate_kbps * 1024 * duration_sec) / 8

    @staticmethod
    def check_compatibility(f):
        """Verifica si un formato es ideal para Premiere/After Effects ✨ o ⚠️"""
        vcodec = f.get('vcodec') or 'none'
        acodec = f.get('acodec') or 'none'
        ext = f.get('ext') or ''

        # Si es solo audio
        if vcodec == 'none':
            if any(c in acodec.lower() for c in EDITOR_FRIENDLY_CRITERIA["compatible_acodecs"]):
                return "✨"
            return "⚠️"
        
        # Si tiene video
        v_ok = any(c in vcodec.lower() for c in EDITOR_FRIENDLY_CRITERIA["compatible_vcodecs"])
        ext_ok = ext.lower() in EDITOR_FRIENDLY_CRITERIA["compatible_exts"]
        
        if v_ok and ext_ok:
            return "✨"
        return "⚠️"

    # ─── Clasificador de Formatos (Cascada de Reglas) ─────────

    @staticmethod
    def classify_format(f):
        """
        Clasifica un formato individual en: 'VIDEO', 'VIDEO_ONLY', 'AUDIO', o 'SKIP'.
        Cascada de reglas ordenada de más específica a más genérica.
        """
        ext = (f.get('ext') or '').lower()
        vcodec = f.get('vcodec') or ''
        acodec = f.get('acodec') or ''
        format_id = (f.get('format_id') or '').lower()
        format_note = (f.get('format_note') or '').lower()
        height = f.get('height')
        width = f.get('width')
        protocol = f.get('protocol') or ''

        # ── REGLA 0: Formatos basura → SKIP
        if ext in ('mhtml', 'html'):
            return 'SKIP'

        # ── REGLA 1: Casos especiales de vcodec literal
        # 'audio only' es un valor crudo de yt-dlp (nunca localizado) - no traducir.
        if vcodec == 'audio only':
            return 'AUDIO'
        if vcodec in ('images', 'slideshow'):
            return 'SKIP'

        # ── REGLA 2: GIF explícito → VIDEO (silencioso)
        if ext == 'gif' or vcodec == 'gif':
            return 'VIDEO'

        # ── REGLA 3: Tiene dimensiones → algún tipo de VIDEO
        if height or width:
            vcodec_unknown = not vcodec or vcodec in ('unknown', 'N/A', '')
            acodec_unknown = not acodec or acodec in ('unknown', 'N/A', '')

            # Ambos códecs desconocidos → asumir combinado (Twitter/X, Twitch)
            if vcodec_unknown and acodec_unknown:
                return 'VIDEO'

            # Audio es explícitamente 'none' → solo video
            if acodec == 'none':
                return 'VIDEO_ONLY'

            # Tiene audio conocido → combinado
            return 'VIDEO'

        # ── REGLA 4: Resolución en format_note (sin dimensiones explícitas)
        res_patterns = ('144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p', '4320p')
        if any(r in format_note for r in res_patterns):
            if acodec == 'none':
                return 'VIDEO_ONLY'
            return 'VIDEO'

        # ── REGLA 5: "audio" explícito en IDs o nota
        if 'audio' in format_id or 'audio' in format_note:
            return 'AUDIO'

        # ── REGLA 6: "video" explícito en IDs o nota
        if 'video' in format_id or 'video' in format_note:
            if acodec == 'none':
                return 'VIDEO_ONLY'
            return 'VIDEO'

        # ── REGLA 7: Extensión de audio conocida
        if ext in AUDIO_EXTENSIONS:
            return 'AUDIO'

        # ── REGLA 8: vcodec=none + acodec real → AUDIO
        if vcodec == 'none' and acodec and acodec not in ('none', '', 'N/A', 'unknown'):
            return 'AUDIO'

        # ── REGLA 9: acodec=none + vcodec real → VIDEO_ONLY
        if acodec == 'none' and vcodec and vcodec not in ('none', '', 'N/A', 'unknown'):
            return 'VIDEO_ONLY'

        # ── REGLA 10: Extensión de video conocida
        if ext in VIDEO_EXTENSIONS:
            # Ambos desconocidos → asumir combinado
            return 'VIDEO'

        # ── REGLA 11: Heurístico por bitrate
        if f.get('tbr') and not f.get('abr'):
            return 'VIDEO'
        if f.get('abr') and not f.get('vbr'):
            return 'AUDIO'

        # ── REGLA 12: Protocolo m3u8/dash (último recurso)
        if 'm3u8' in protocol or 'dash' in protocol:
            return 'VIDEO'

        # Desconocido
        logger.warning(f"FormatManager: Formato sin clasificar: {f.get('format_id')} "
                       f"(vcodec={vcodec}, acodec={acodec}, ext={ext})")
        return 'SKIP'

    # ─── Parser Principal ─────────────────────────────────────

    @staticmethod
    def parse_formats(info_dict):
        """
        Analiza el info_dict y devuelve (video_options, audio_options, has_audio_source).
        
        - video_options: lista de dicts para el menú de video
        - audio_options: lista de dicts para el menú de audio
        - has_audio_source: bool, True si hay al menos 1 fuente de audio disponible
        """
        formats = info_dict.get('formats', [])
        duration = info_dict.get('duration', 0)

        # ── PASO 1: Clasificar todos los formatos ──
        audio_only_formats = []
        video_formats = []       # Combinados (VIDEO) y solo-video (VIDEO_ONLY)
        has_audio_source = False

        for f in formats:
            fmt_type = FormatManager.classify_format(f)

            if fmt_type == 'AUDIO':
                audio_only_formats.append(f)
                has_audio_source = True
            elif fmt_type in ('VIDEO', 'VIDEO_ONLY'):
                video_formats.append(f)
                # Un video combinado también es fuente de audio
                if fmt_type == 'VIDEO':
                    has_audio_source = True
            # 'SKIP' se ignora

        # ── PASO 2: Crear opciones de audio ──
        audio_options = [FormatManager._create_audio_option(f, duration) for f in audio_only_formats]

        # ── PASO 3: Agrupar videos por características visuales ──
        # La key incluye bitrate redondeado para no colapsar variantes de Facebook
        visual_groups = {}  # (h, fps, vc, tbr_rounded) -> [formats]

        for f in video_formats:
            h = f.get('height') or 0
            fps = f.get('fps') or 0
            vc = (f.get('vcodec') or '').split('.')[0]  # Solo familia de codec
            tbr = f.get('tbr') or 0
            tbr_rounded = round(tbr / 100) * 100 if tbr > 0 else 0

            v_key = (h, fps, vc, tbr_rounded)
            if v_key not in visual_groups:
                visual_groups[v_key] = []
            visual_groups[v_key].append(f)

        video_options = []
        for v_key, group in visual_groups.items():
            # ¿Multi-idioma? Solo si hay 2+ idiomas DIFERENTES en el grupo
            unique_langs = set(f.get('language') for f in group if f.get('language'))

            if len(unique_langs) > 1:
                # Colapsar el grupo → 1 entrada de video con audios internos
                base_f = group[0]
                v_opt = FormatManager._create_video_option(base_f, duration, is_multi=True)
                internal = [FormatManager._create_audio_option(f, duration) for f in group]
                # Ordenar por prioridad de idioma (mismo orden que la lista principal)
                internal.sort(key=lambda x: (
                    LANGUAGE_ORDER.get((x.get('lang') or 'und').lower(), DEFAULT_PRIORITY),
                    -x.get('tbr', 0)
                ))
                v_opt['internal_audios'] = internal
                video_options.append(v_opt)
            else:
                # Cada formato es una entrada separada
                for f in group:
                    video_options.append(FormatManager._create_video_option(f, duration))

        # ── PASO 4: Fallback si no hay nada ──
        if not video_options and not audio_options:
            generic = {
                'format_id': 'default',
                'ext': info_dict.get('ext', 'mp4'),
                'vcodec': info_dict.get('vcodec', 'h264'),
                'acodec': info_dict.get('acodec', 'aac'),
                'resolution': info_dict.get('resolution', 'Calidad Única'),
                'filesize': info_dict.get('filesize', 0)
            }
            video_options.append(FormatManager._create_video_option(generic, duration, force_combined=True))

        # ── PASO 5: Ordenar ──
        video_options.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0), reverse=True)

        audio_options.sort(key=lambda x: (
            LANGUAGE_ORDER.get((x.get('lang') or 'und').lower(), DEFAULT_PRIORITY),
            -x.get('tbr', 0)
        ))

        return video_options, audio_options, has_audio_source

    # ─── Constructores de Opciones ────────────────────────────

    @staticmethod
    def _create_video_option(f, duration, force_combined=False, is_multi=False):
        res = f.get('resolution') or f"{f.get('width', '?')}x{f.get('height', '?')}"
        fps = f.get('fps')

        # Salvaguardas contra None
        raw_vcodec = f.get('vcodec') or 'unknown'
        raw_acodec = f.get('acodec') or ''
        ext = f.get('ext') or 'mp4'

        # Determinar si es combinado
        acodec_effective = raw_acodec if raw_acodec not in ('none', '') else 'none'
        vcodec_effective = raw_vcodec if raw_vcodec not in ('none', '') else 'unknown'
        
        # Regla especial: si ambos son desconocidos (Twitter), asumir combinado
        both_unknown = (vcodec_effective == 'unknown' and acodec_effective == 'none')
        is_combined = force_combined or is_multi or (acodec_effective != 'none') or both_unknown

        # Construir string de descripción
        fps_str = f"{int(fps)}fps" if fps else ""
        codec_str = raw_vcodec.split('.')[0]

        # Peso
        size_bytes = f.get('filesize') or f.get('filesize_approx') or FormatManager.estimate_size(f.get('tbr'), duration)
        size_str = FormatManager.get_friendly_size(size_bytes)

        tags = []
        if is_multi:
            tags.append("[Multi-Idioma]")
        elif is_combined:
            tags.append("[Combinado]")

        tag_str = " ".join(tags) + " " if tags else ""

        label = f"{tag_str}{res} {fps_str} | {codec_str} | {ext.upper()}"
        if size_str:
            label += f" | {size_str}"

        label += f" {FormatManager.check_compatibility(f)}"

        return {
            'id': f.get('format_id'),
            'label': label,
            'height': f.get('height') or 0,
            'tbr': f.get('tbr') or 0,
            'is_combined': is_combined,
            'is_multi': is_multi,
            'has_video': True,
            'has_audio': is_combined,
            'lang': f.get('language'),
            'ext': ext,
            'vcodec': raw_vcodec,
            'acodec': raw_acodec,
            'raw': f
        }

    @staticmethod
    def _create_audio_option(f, duration):
        acodec = f.get('acodec') or 'unknown'
        ext = f.get('ext') or 'm4a'
        abr = f.get('abr') or f.get('tbr')
        asr = f.get('asr')
        lang_code = f.get('language') or 'und'

        # Normalizar código de idioma
        norm_code = lang_code.replace('_', '-').lower()
        lang_name = LANG_CODE_MAP.get(norm_code, LANG_CODE_MAP.get(norm_code.split('-')[0], lang_code.upper()))

        # Peso
        size_bytes = f.get('filesize') or f.get('filesize_approx') or FormatManager.estimate_size(abr, duration)
        size_str = FormatManager.get_friendly_size(size_bytes)

        # Formatear kbps y khz
        abr_str = f"{int(abr)}kbps" if abr else ""
        asr_str = f"{float(asr)/1000:.1f}kHz" if asr else ""
        codec_str = acodec.split('.')[0]

        # Nota DRC
        note = (f.get('format_note') or '').lower()
        drc_tag = " (DRC)" if 'drc' in note else ""

        label = f"{lang_name} | {abr_str} | {asr_str} | {codec_str} | {ext.upper()}{drc_tag}"
        if size_str:
            label += f" | {size_str}"

        label += f" {FormatManager.check_compatibility(f)}"

        return {
            'id': f.get('format_id'),
            'label': label,
            'tbr': abr or 0,
            'ext': ext,
            'lang': lang_code,
            'has_video': f.get('vcodec') not in (None, 'none'),
            'has_audio': True,
            'raw': f
        }
