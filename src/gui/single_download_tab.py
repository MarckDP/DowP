from flask import Flask, jsonify, request
from flask_socketio import SocketIO
import threading
import webbrowser
from tkinter import messagebox
import tkinter
import customtkinter as ctk
from customtkinter import filedialog
from PIL import Image
import requests
from io import BytesIO
import gc
import os
import re
import sys
from pathlib import Path
import subprocess
import json
import time
import shutil
import platform
import yt_dlp
import io
from datetime import datetime, timedelta

# Importar nuestros otros módulos
from src.core.downloader import get_video_info, download_media, apply_site_specific_rules
from src.core.processor import FFmpegProcessor, CODEC_PROFILES
from src.core.exceptions import UserCancelledError, LocalRecodeFailedError, PlaylistDownloadError # <-- MODIFICAR
from src.core.processor import clean_and_convert_vtt_to_srt
from .dialogs import ConflictDialog, LoadingWindow, CompromiseDialog, SimpleMessageDialog, SavePresetDialog, PlaylistErrorDialog, Tooltip
from src.core.constants import (
    VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, SINGLE_STREAM_AUDIO_CONTAINERS,
    FORMAT_MUXER_MAP, LANG_CODE_MAP, LANGUAGE_ORDER,
    DEFAULT_PRIORITY, EDITOR_FRIENDLY_CRITERIA, COMPATIBILITY_RULES
)
from contextlib import redirect_stdout
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
from main import PROJECT_ROOT, MODELS_DIR
# -------------------------------------------------

class SingleDownloadTab(ctk.CTkFrame):
    """
    Esta clase contendrá TODA la UI y la lógica de la
    pestaña de descarga única.
    """
    DOWNLOAD_BTN_COLOR = "#28A745"       
    DOWNLOAD_BTN_HOVER = "#218838"       
    PROCESS_BTN_COLOR = "#6F42C1"        
    PROCESS_BTN_HOVER = "#59369A"        

    ANALYZE_BTN_COLOR = "#007BFF"        
    ANALYZE_BTN_HOVER = "#0069D9"        

    
    CANCEL_BTN_COLOR = "#DC3545"         
    CANCEL_BTN_HOVER = "#C82333"         
    
    DISABLED_TEXT_COLOR = "#D3D3D3"
    DISABLED_FG_COLOR = "#565b5f" 

    def __init__(self, master, app):
        """
        Inicializa la pestaña.
        'master' es el contenedor de la pestaña.
        'app' es la referencia a la ventana principal (MainWindow).
        """
        super().__init__(master, fg_color="transparent")
        self.app = app 
        self.is_initializing = True 
        self.pack(expand=True, fill="both")
        
        # Hacemos "atajos" a objetos globales que usaremos mucho
        self.ffmpeg_processor = self.app.ffmpeg_processor
        self.cancellation_event = self.app.cancellation_event

        # --- VARIABLES DE ESTADO PEGADAS AQUÍ ---
        self.original_video_width = 0
        self.original_video_height = 0
        self.has_video_streams = False
        self.has_audio_streams = False
        self.analysis_is_complete = False

        # (Omitimos 'geometry', 'minsize', 'ctk', 'server_thread'...)

        self.combined_variants = {}  # 🆕 Diccionario para variantes multiidioma
        self.combined_audio_map = {}  # 🆕 Mapeo de idiomas seleccionados
        self.video_formats = {}
        self.audio_formats = {}
        self.subtitle_formats = {} 
        self.local_file_path = None
        self.thumbnail_label = None
        self.pil_image = None
        self.last_download_path = None
        self.video_duration = 0
        self.video_id = None
        self.analysis_cache = {} 
        self.CACHE_TTL = 300
        self.active_subprocess_pid = None 
        self.active_operation_thread = None
        self.release_page_url = None
        self.recode_settings = {}
        self.all_subtitles = {}
        self.current_subtitle_map = {}
        self.apply_quick_preset_checkbox_state = False
        self.keep_original_quick_saved = True
        self.analysis_was_playlist = False

        self.active_downloads_state = {
            "ffmpeg": {"text": "", "value": 0.0, "active": False},
            "deno": {"text": "", "value": 0.0, "active": False},
            "poppler": {"text": "", "value": 0.0, "active": False},
            "inkscape": {"text": "", "value": 0.0, "active": False},
            "rembg": {"text": "", "value": 0.0, "active": False}
        }

        self.recode_compatibility_status = "valid"
        self.original_analyze_text = "Analizar"

        self.original_analyze_command = self.start_analysis_thread # <-- Arreglaremos esto
        self.original_analyze_fg_color = None
        self.original_download_text = "Iniciar Descarga"
        self.original_download_command = self.start_download_thread # <-- Arreglaremos esto
        self.original_download_fg_color = None

        self._initialize_presets_file()
        presets_data = self._load_presets()
        self.built_in_presets = presets_data.get("built_in_presets", {})
        self.custom_presets = presets_data.get("custom_presets", [])

        self._create_widgets()
        self._initialize_ui_settings()

    def _get_ctk_fg_color(self, ctk_widget):
        """
        Obtiene el color de fondo de un widget de CustomTkinter según el tema actual.
        """
        try:
            fg_color = ctk_widget._fg_color
            if isinstance(fg_color, (tuple, list)):
                # CustomTkinter usa tuplas (color_claro, color_oscuro)
                # Índice 1 = color oscuro (modo Dark)
                appearance_mode = ctk.get_appearance_mode()
                return fg_color[1] if appearance_mode == "Dark" else fg_color[0]
            return fg_color
        except Exception as e:
            print(f"DEBUG: Error obteniendo color: {e}")
            return "#2B2B2B"  # Fallback gris oscuro

    def _initialize_ui_settings(self):

        self.output_path_entry.delete(0, 'end')
        
        # --- INICIO DE LA MODIFICACIÓN ---
        if self.app.default_download_path:
            self.output_path_entry.insert(0, self.app.default_download_path)
        else:
            # Fallback a la carpeta de Descargas si la config está vacía
            try:
                from pathlib import Path # Importar aquí para uso local
                downloads_path = Path.home() / "Downloads"
                if downloads_path.exists() and downloads_path.is_dir():
                    self.output_path_entry.insert(0, str(downloads_path))
                    # Actualizar el path global para que se guarde al cerrar
                    self.app.default_download_path = str(downloads_path) 
            except Exception as e:
                print(f"No se pudo establecer la carpeta de descargas por defecto: {e}")
        # --- FIN DE LA MODIFICACIÓN ---

        self.cookie_mode_menu.set(self.app.cookies_mode_saved)

        if self.app.cookies_path: 
            self.cookie_path_entry.insert(0, self.app.cookies_path) 
        
        # ESTAS LÍNEAS VAN AQUÍ (fuera del if)
        self.browser_var.set(self.app.selected_browser_saved) 
        self.browser_profile_entry.insert(0, self.app.browser_profile_saved)
        self.on_cookie_mode_change(self.app.cookies_mode_saved)

        self.auto_download_subtitle_check.deselect()

        if self.app.apply_quick_preset_checkbox_state: 
            self.apply_quick_preset_checkbox.select()
        else:
            self.apply_quick_preset_checkbox.deselect()

        self.apply_quick_preset_checkbox.deselect()

        self._on_quick_recode_toggle()

        if self.app.keep_original_quick_saved: 
            self.keep_original_quick_checkbox.select()
        else:
            self.keep_original_quick_checkbox.deselect()
        self.toggle_manual_subtitle_button()
        if self.app.recode_settings.get("keep_original", True): 
            self.keep_original_checkbox.select()
        else:
            self.keep_original_checkbox.deselect()
        self.recode_video_checkbox.deselect()
        self.recode_audio_checkbox.deselect()
        self._toggle_recode_panels()
        self._populate_preset_menu()
        
        # 🆕 CRÍTICO: Forzar la visibilidad del panel de recodificación al inicio
        self.recode_main_frame.pack(pady=(10, 0), padx=5, fill="both", expand=True)
        print("DEBUG: Panel de recodificación forzado a mostrarse en inicialización")
        
        self.app.after(100, self._update_save_preset_visibility)
        self.enable_drag_and_drop()
        self.is_initializing = False
        
    def _create_widgets(self):

        url_frame = ctk.CTkFrame(self)
        url_frame.pack(pady=10, padx=10, fill="x")
        ctk.CTkLabel(url_frame, text="URL:").pack(side="left", padx=(10, 5))
        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Pega la URL aquí...")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.url_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.url_entry))
        self.url_entry.bind("<Return>", self.start_analysis_thread)
        self.url_entry.bind("<KeyRelease>", self.update_download_button_state)
        self.url_entry.bind("<<Paste>>", lambda e: self.app.after(50, self.update_download_button_state))
        self.analyze_button = ctk.CTkButton(url_frame, text=self.original_analyze_text, command=self.original_analyze_command, 
                                     fg_color=self.ANALYZE_BTN_COLOR, hover_color=self.ANALYZE_BTN_HOVER)
        self.analyze_button.pack(side="left", padx=(5, 10))
        self.original_analyze_fg_color = self.ANALYZE_BTN_COLOR
        self.analyze_button.pack(side="left", padx=(5, 10))
        self.original_analyze_fg_color = self.analyze_button.cget("fg_color")
        
        # Creamos el frame pero NO lo empaquetamos todavía
        self.info_frame = ctk.CTkFrame(self) 
        # (Nota: cambié info_frame a self.info_frame para poder acceder al final, 
        # pero si no quieres cambiar todas las referencias, guárdalo en una variable temporal al final)
        
        # Para no romper tu código existente que usa 'info_frame' variable local:
        info_frame = ctk.CTkFrame(self)
        self.info_frame_ref = info_frame # Guardamos referencia para el final
        
        left_column_container = ctk.CTkFrame(info_frame, fg_color="transparent")
        left_column_container.pack(side="left", padx=10, pady=10, fill="y", anchor="n")
        
        self.thumbnail_container = ctk.CTkFrame(left_column_container, width=320, height=180)
        self.thumbnail_container.pack(pady=(0, 5))
        self.thumbnail_container.pack_propagate(False)

        # ✅ NUEVO: Frame Tkinter nativo para Drag & Drop
        # Este frame se coloca ENCIMA del CTkFrame y captura los eventos de DnD
        import tkinter  # Asegúrate de tenerlo importado al inicio del archivo

        self.dnd_overlay = tkinter.Frame(
            self.thumbnail_container,
            bg=self.thumbnail_container._apply_appearance_mode(self.thumbnail_container._fg_color),  # Mismo color de fondo
            width=320,
            height=180
        )
        self.dnd_overlay.place(x=0, y=0, relwidth=1, relheight=1)  # Cubre todo el contenedor
        self.dnd_overlay.pack_propagate(False)

        self.create_placeholder_label()

        thumbnail_actions_frame = ctk.CTkFrame(left_column_container)
        thumbnail_actions_frame.pack(fill="x")

        # Frame para los botones (en fila)
        thumbnail_buttons_frame = ctk.CTkFrame(thumbnail_actions_frame, fg_color="transparent")
        thumbnail_buttons_frame.pack(fill="x", padx=10, pady=5)
        thumbnail_buttons_frame.grid_columnconfigure((0, 1), weight=1)

        # Botón descargar miniatura (izquierda)
        self.save_thumbnail_button = ctk.CTkButton(
            thumbnail_buttons_frame, 
            text="Descargar Miniatura", 
            state="disabled", 
            command=self.save_thumbnail
        )
        self.save_thumbnail_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        # Botón enviar a H.I. (derecha)
        self.send_thumbnail_to_imagetools_button = ctk.CTkButton(
            thumbnail_buttons_frame,
            text="Enviar a H.I.",
            state="disabled",
            command=self._send_thumbnail_to_image_tools,
        )
        self.send_thumbnail_to_imagetools_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # ✅ MODIFICADO: Checkbox debajo de los botones (sin usar 'after')
        self.auto_save_thumbnail_check = ctk.CTkCheckBox(
            thumbnail_actions_frame, 
            text="Descargar miniatura con el video", 
            command=self.toggle_manual_thumbnail_button
        )
        self.auto_save_thumbnail_check.pack(padx=10, pady=(0, 5), anchor="w")

        options_scroll_frame = ctk.CTkScrollableFrame(left_column_container)
        options_scroll_frame.pack(pady=10, fill="both", expand=True)
        ctk.CTkLabel(options_scroll_frame, text="Descargar Fragmento", font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=10, pady=(5, 2))
        fragment_frame = ctk.CTkFrame(options_scroll_frame)
        fragment_frame.pack(fill="x", padx=5, pady=(0, 10))
        self.fragment_checkbox = ctk.CTkCheckBox(fragment_frame, text="Activar corte de fragmento", command=lambda: (self._toggle_fragment_panel(), self.update_download_button_state()))
        self.fragment_checkbox.pack(padx=10, pady=5, anchor="w")
        self.fragment_options_frame = ctk.CTkFrame(fragment_frame, fg_color="transparent")
        self.fragment_options_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.fragment_options_frame, text="Inicio:").grid(row=0, column=0, padx=(0, 5), pady=5, sticky="w")
        start_time_frame = ctk.CTkFrame(self.fragment_options_frame, fg_color="transparent")
        start_time_frame.grid(row=0, column=1, pady=5, sticky="ew")
        self.start_h = ctk.CTkEntry(start_time_frame, width=40, placeholder_text="00")
        self.start_m = ctk.CTkEntry(start_time_frame, width=40, placeholder_text="00")
        self.start_s = ctk.CTkEntry(start_time_frame, width=40, placeholder_text="00")
        self.start_h.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(start_time_frame, text=":", font=ctk.CTkFont(size=14)).pack(side="left", padx=5)
        self.start_m.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(start_time_frame, text=":", font=ctk.CTkFont(size=14)).pack(side="left", padx=5)
        self.start_s.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(self.fragment_options_frame, text="Final:").grid(row=1, column=0, padx=(0, 5), pady=5, sticky="w")
        end_time_frame = ctk.CTkFrame(self.fragment_options_frame, fg_color="transparent")
        end_time_frame.grid(row=1, column=1, pady=5, sticky="ew")
        self.end_h = ctk.CTkEntry(end_time_frame, width=40, placeholder_text="00")
        self.end_m = ctk.CTkEntry(end_time_frame, width=40, placeholder_text="00")
        self.end_s = ctk.CTkEntry(end_time_frame, width=40, placeholder_text="00")
        self.end_h.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(end_time_frame, text=":", font=ctk.CTkFont(size=14)).pack(side="left", padx=5)
        self.end_m.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(end_time_frame, text=":", font=ctk.CTkFont(size=14)).pack(side="left", padx=5)
        self.end_s.pack(side="left", fill="x", expand=True)

        # 1. Checkbox: Corte Preciso
        self.precise_clip_check = ctk.CTkCheckBox(
            self.fragment_options_frame, 
            text="Corte Preciso (Lento/Recodificar)",
            command=self._on_precise_clip_toggle  # <-- VINCULACIÓN
        )
        self.precise_clip_check.grid(row=3, column=0, columnspan=2, pady=(5,0), sticky="w")
        Tooltip(self.precise_clip_check, "Activado: Recodifica bordes para exactitud (Lento).\nDesactivado: Corta en keyframes (Rápido, menos preciso).", delay_ms=1000)

        # 2. NUEVO Checkbox: Descargar Completo (Rápido)
        self.force_full_download_check = ctk.CTkCheckBox(
            self.fragment_options_frame, 
            text="Descargar completo para cortar (Rápido)",
            command=self._on_force_full_download_toggle # <-- VINCULACIÓN
        )
        self.force_full_download_check.grid(row=4, column=0, columnspan=2, pady=(5,0), sticky="w")
        
        Tooltip(self.force_full_download_check, 
                "Recomendado para internet rápido.\n"
                "Baja todo el video a máxima velocidad y lo corta en tu PC.\n"
                "Evita la lentitud del procesamiento en la nube de YouTube.", 
                delay_ms=1000)

        # 3. Conservar completo (Mover a row=5)
        self.keep_original_on_clip_check = ctk.CTkCheckBox(
            self.fragment_options_frame, 
            text="Conservar completo (solo modo URL)",
            command=self._on_keep_original_clip_toggle # <-- VINCULACIÓN AÑADIDA
        )
        self.keep_original_on_clip_check.grid(row=5, column=0, columnspan=2, pady=(5,0), sticky="w")
        
        # 4. Warning Label (Mover a row=6)
        self.time_warning_label = ctk.CTkLabel(self.fragment_options_frame, text="", text_color="orange", wraplength=280, justify="left")
        self.time_warning_label.grid(row=6, column=0, columnspan=2, pady=(5,0), sticky="w")

        ctk.CTkLabel(options_scroll_frame, text="Subtítulos", font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=10, pady=(5, 2))
        subtitle_options_frame = ctk.CTkFrame(options_scroll_frame)
        subtitle_options_frame.pack(fill="x", padx=5, pady=(0, 10))
        subtitle_selection_frame = ctk.CTkFrame(subtitle_options_frame, fg_color="transparent")
        subtitle_selection_frame.pack(fill="x", padx=10, pady=(0, 5))
        subtitle_selection_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(subtitle_selection_frame, text="Idioma:").grid(row=0, column=0, padx=(0, 10), pady=5, sticky="w")
        self.subtitle_lang_menu = ctk.CTkOptionMenu(subtitle_selection_frame, values=["-"], state="disabled", command=self.on_language_change)
        self.subtitle_lang_menu.grid(row=0, column=1, pady=5, sticky="ew")
        ctk.CTkLabel(subtitle_selection_frame, text="Formato:").grid(row=1, column=0, padx=(0, 10), pady=5, sticky="w")
        self.subtitle_type_menu = ctk.CTkOptionMenu(subtitle_selection_frame, values=["-"], state="disabled", command=self.on_subtitle_selection_change)
        self.subtitle_type_menu.grid(row=1, column=1, pady=5, sticky="ew")
        self.save_subtitle_button = ctk.CTkButton(subtitle_options_frame, text="Descargar Subtítulos", state="disabled", command=self.save_subtitle)
        self.save_subtitle_button.pack(fill="x", padx=10, pady=5)
        self.auto_download_subtitle_check = ctk.CTkCheckBox(subtitle_options_frame, text="Descargar subtítulos con el video", command=self.toggle_manual_subtitle_button)
        self.auto_download_subtitle_check.pack(padx=10, pady=5, anchor="w")
        self.clean_subtitle_check = ctk.CTkCheckBox(subtitle_options_frame, text="Convertir y estandarizar a formato SRT")
        self.clean_subtitle_check.pack(padx=10, pady=(0, 5), anchor="w")

        cookies_label = ctk.CTkLabel(options_scroll_frame, text="Cookies", font=ctk.CTkFont(weight="bold"))
        cookies_label.pack(fill="x", padx=10, pady=(5, 2))
        
        # --- AÑADIR ESTAS LÍNEAS (TOOLTIP 6) ---
        cookies_tooltip_text = "Configura las cookies para acceder a contenido protegido.\n\nÚtil para:\n• Videos con restricción de edad\n• Videos privados o solo para suscriptores\n• Contenido que requiere iniciar sesión"
        Tooltip(cookies_label, cookies_tooltip_text, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        cookie_options_frame = ctk.CTkFrame(options_scroll_frame)
        cookie_options_frame.pack(fill="x", padx=5, pady=(0, 10))

        # 🔧 MODIFICADO: Agregar opción de ayuda al menú
        self.cookie_mode_menu = ctk.CTkOptionMenu(
            cookie_options_frame, 
            values=["No usar", "Archivo Manual...", "Desde Navegador", "¿Cómo obtener cookies?"], 
            command=self.on_cookie_mode_change
        )
        self.cookie_mode_menu.pack(fill="x", padx=10, pady=(0, 5))

        self.manual_cookie_frame = ctk.CTkFrame(cookie_options_frame, fg_color="transparent")
        self.cookie_path_entry = ctk.CTkEntry(self.manual_cookie_frame, placeholder_text="Ruta al archivo cookies.txt...")
        self.cookie_path_entry.pack(fill="x")
        self.cookie_path_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.cookie_path_entry))
        self.cookie_path_entry.bind("<KeyRelease>", self._on_cookie_detail_change)
        self.select_cookie_file_button = ctk.CTkButton(self.manual_cookie_frame, text="Elegir Archivo...", command=lambda: self.select_cookie_file())
        self.select_cookie_file_button.pack(fill="x", pady=(5,0))

        self.browser_options_frame = ctk.CTkFrame(cookie_options_frame, fg_color="transparent")
        ctk.CTkLabel(self.browser_options_frame, text="Navegador:").pack(padx=10, pady=(5,0), anchor="w")
        self.browser_var = ctk.StringVar(value=self.app.selected_browser_saved) # <--- ¡CORREGIDO!
        self.browser_menu = ctk.CTkOptionMenu(self.browser_options_frame, values=["chrome", "firefox", "edge", "opera", "vivaldi", "brave"], variable=self.browser_var, command=self._on_cookie_detail_change)
        self.browser_menu.pack(fill="x", padx=10)


        ctk.CTkLabel(self.browser_options_frame, text="Perfil (Opcional):").pack(padx=10, pady=(5,0), anchor="w")
        self.browser_profile_entry = ctk.CTkEntry(self.browser_options_frame, placeholder_text="Ej: Default, Profile 1")
        self.browser_profile_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.browser_profile_entry))
        self.browser_profile_entry.pack(fill="x", padx=10)
        self.browser_profile_entry.bind("<KeyRelease>", self._on_cookie_detail_change)
        cookie_advice_label = ctk.CTkLabel(self.browser_options_frame, text=" ⓘ Si falla, cierre el navegador por completo. \n ⓘ Para Chrome/Edge/Brave,\n se recomienda usar la opción 'Archivo Manual'", font=ctk.CTkFont(size=11), text_color="orange", justify="left")
        cookie_advice_label.pack(pady=(10, 5), padx=10, fill="x", anchor="w")

        ctk.CTkLabel(options_scroll_frame, text="Mantenimiento", font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=10, pady=(5, 2))
        maintenance_frame = ctk.CTkFrame(options_scroll_frame)
        maintenance_frame.pack(fill="x", padx=5, pady=(0, 10))
        maintenance_frame.grid_columnconfigure(0, weight=1)

        self.app_status_label = ctk.CTkLabel(maintenance_frame, text=f"DowP v{self.app.APP_VERSION} - Verificando...", justify="left")
        self.app_status_label.grid(row=0, column=0, padx=10, pady=(5, 5), sticky="ew")

        self.update_app_button = ctk.CTkButton(maintenance_frame, text="Buscar Actualización", state="disabled", command=self._open_release_page)
        self.update_app_button.grid(row=1, column=0, padx=10, pady=(0, 15), sticky="ew")

        self.ffmpeg_status_label = ctk.CTkLabel(maintenance_frame, text="FFmpeg: Verificando...", wraplength=280, justify="left")
        self.ffmpeg_status_label.grid(row=2, column=0, padx=10, pady=(5,5), sticky="ew") 
        self.update_ffmpeg_button = ctk.CTkButton(maintenance_frame, text="Buscar Actualizaciones de FFmpeg", command=self.manual_ffmpeg_update_check)
        self.update_ffmpeg_button.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="ew")

        self.deno_status_label = ctk.CTkLabel(maintenance_frame, text="Deno: Verificando...", wraplength=280, justify="left")
        self.deno_status_label.grid(row=4, column=0, padx=10, pady=(5,5), sticky="ew") 
        self.update_deno_button = ctk.CTkButton(maintenance_frame, text="Buscar Actualizaciones de Deno", command=self.manual_deno_update_check)
        self.update_deno_button.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")

        # --- SECCIÓN POPPLER ---
        self.poppler_status_label = ctk.CTkLabel(maintenance_frame, text="Poppler: Verificando...", wraplength=280, justify="left")
        self.poppler_status_label.grid(row=6, column=0, padx=10, pady=(5,5), sticky="ew") 
        self.update_poppler_button = ctk.CTkButton(maintenance_frame, text="Buscar Actualizaciones de Poppler", command=self.manual_poppler_update_check)
        self.update_poppler_button.grid(row=7, column=0, padx=10, pady=(0, 10), sticky="ew")

        # --- SECCIÓN INKSCAPE ---
        self.inkscape_status_label = ctk.CTkLabel(
            maintenance_frame, 
            text="Inkscape: Verificando...", 
            wraplength=280, 
            justify="left"
        )
        self.inkscape_status_label.grid(row=8, column=0, padx=10, pady=(5,5), sticky="ew") 
        
        # Botón "Recargar" por si metes los archivos con la app abierta
        self.check_inkscape_button = ctk.CTkButton(
            maintenance_frame, 
            text="Verificar Inkscape", 
            command=self.manual_inkscape_check
        )
        self.check_inkscape_button.grid(row=9, column=0, padx=10, pady=(0, 10), sticky="ew")

        # --- SECCIÓN GHOSTSCRIPT (NUEVO) ---
        self.ghostscript_status_label = ctk.CTkLabel(
            maintenance_frame, 
            text="Ghostscript: Verificando...", 
            wraplength=280, 
            justify="left"
        )
        self.ghostscript_status_label.grid(row=10, column=0, padx=10, pady=(5,5), sticky="ew") 
        
        self.check_ghostscript_button = ctk.CTkButton(
            maintenance_frame, 
            text="Verificar Ghostscript", 
            command=self.manual_ghostscript_check
        )
        self.check_ghostscript_button.grid(row=11, column=0, padx=10, pady=(0, 10), sticky="ew")

        # --- SECCIÓN MODELOS IA (rembg) ---
        # --- SECCIÓN MODELOS IA (rembg) ---
        self.rembg_status_label = ctk.CTkLabel(
            maintenance_frame, 
            text="Modelos IA: Pendiente...", 
            wraplength=280, 
            justify="left"
        )
        self.rembg_status_label.grid(row=12, column=0, padx=10, pady=(5, 5), sticky="ew") # Reduje pady inferior

        # ✅ NUEVO BOTÓN
        self.open_models_folder_button = ctk.CTkButton(
            maintenance_frame,
            text="Abrir Carpeta de Modelos",
            command=self._open_ai_models_folder,
            fg_color="#555555", hover_color="#444444", # Color gris discreto
            height=24
        )
        self.open_models_folder_button.grid(row=13, column=0, padx=10, pady=(0, 15), sticky="ew")

        details_frame = ctk.CTkFrame(info_frame)
        details_frame.pack(side="left", fill="both", expand=True, padx=(0,10), pady=10)
        ctk.CTkLabel(details_frame, text="Título:", anchor="w").pack(fill="x", padx=5, pady=(5,0))
        self.title_entry = ctk.CTkEntry(details_frame, font=("", 14))
        self.title_entry.pack(fill="x", padx=5, pady=(0,10))
        self.title_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.title_entry))

        options_frame = ctk.CTkFrame(details_frame)
        options_frame.pack(fill="x", padx=5, pady=5)
        
        # --- MODIFICACIÓN: Asignar la etiqueta a una variable ---
        mode_label = ctk.CTkLabel(options_frame, text="Modo:")
        mode_label.pack(side="left", padx=(0, 10))
        # --- FIN DE LA MODIFICACIÓN ---
        
        self.mode_selector = ctk.CTkSegmentedButton(options_frame, values=["Video+Audio", "Solo Audio"], command=self.on_mode_change)
        self.mode_selector.set("Video+Audio")
        self.mode_selector.pack(side="left", expand=True, fill="x")

        # --- AÑADIR ESTAS LÍNEAS (TOOLTIP 13) ---
        mode_tooltip_text = "• Video+Audio: Descarga el video y el audio juntos.\n• Solo Audio: Descarga únicamente la pista de audio.\n\nEsta selección filtra las opciones de calidad y recodificación."
        Tooltip(mode_label, mode_tooltip_text, delay_ms=1000)
        
        self.video_quality_label = ctk.CTkLabel(details_frame, text="Calidad de Video:", anchor="w")
        self.video_quality_menu = ctk.CTkOptionMenu(details_frame, state="disabled", values=["-"], command=self.on_video_quality_change)
        self.audio_options_frame = ctk.CTkFrame(details_frame, fg_color="transparent")
        self.audio_quality_label = ctk.CTkLabel(self.audio_options_frame, text="Calidad de Audio:", anchor="w")
        self.audio_quality_menu = ctk.CTkOptionMenu(self.audio_options_frame, state="disabled", values=["-"], command=lambda _: (self._update_warnings(), self._validate_recode_compatibility()))
        self.use_all_audio_tracks_check = ctk.CTkCheckBox(self.audio_options_frame, text="Aplicar la recodificación a todas las pistas de audio", command=self._on_use_all_audio_tracks_change)

        multi_track_tooltip_text = "Aplica la recodificación seleccionada a TODAS las pistas de audio por separado (no las fusiona).\n\n• Advertencia: Esta función depende del formato de salida. No todos los contenedores (ej: `.mp3`) admiten audio multipista."
        Tooltip(self.use_all_audio_tracks_check, multi_track_tooltip_text, delay_ms=1000)

        self.audio_quality_label.pack(fill="x", padx=5, pady=(10,0))
        self.audio_quality_menu.pack(fill="x", padx=5, pady=(0,5))
        legend_text = (         
            "Guía de etiquetas en la lista:\n"
            "✨ Ideal: Formato óptimo para editar sin conversión.\n"
            "⚠️ Recodificar: Formato no compatible con editores."
        )
        self.format_warning_label = ctk.CTkLabel(
            details_frame, 
            text=legend_text, 
            text_color="gray", 
            font=ctk.CTkFont(size=12, weight="normal"), 
            wraplength=400, 
            justify="left"
        )
        self.recode_main_frame = ctk.CTkScrollableFrame(details_frame)

        recode_title_label = ctk.CTkLabel(self.recode_main_frame, text="Opciones de Recodificación", font=ctk.CTkFont(weight="bold"))
        recode_title_label.pack(pady=(5,10))

        recode_tooltip_text = "Permite convertir el archivo a un formato diferente.\nÚtil para mejorar la compatibilidad con editores \n(ej: Premiere, After Effects) o para reducir el tamaño del archivo."
        Tooltip(recode_title_label, recode_tooltip_text, delay_ms=1000)

        recode_mode_frame = ctk.CTkFrame(self.recode_main_frame, fg_color="transparent")
        recode_mode_frame.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(recode_mode_frame, text="Modo:").pack(side="left", padx=(0, 10))
        self.recode_mode_selector = ctk.CTkSegmentedButton(recode_mode_frame, values=["Modo Rápido", "Modo Manual", "Modo Extraer"], command=self._on_recode_mode_change)
        self.recode_mode_selector.pack(side="left", expand=True, fill="x")

        self.recode_quick_frame = ctk.CTkFrame(self.recode_main_frame)

        self.apply_quick_preset_checkbox = ctk.CTkCheckBox(
            self.recode_quick_frame, 
            text="Recodificación no disponible (Detectando FFmpeg...)", 
            command=self._on_quick_recode_toggle,
            state="disabled" 
        )
        self.apply_quick_preset_checkbox.pack(anchor="w", padx=10, pady=(5, 5))
        self.apply_quick_preset_checkbox.deselect()
        
        self.quick_recode_options_frame = ctk.CTkFrame(self.recode_quick_frame, fg_color="transparent")
        
        # --- MODIFICACIÓN: Asignar la etiqueta a una variable ---
        preset_label = ctk.CTkLabel(self.quick_recode_options_frame, text="Preset de Conversión:", font=ctk.CTkFont(weight="bold"))
        preset_label.pack(pady=10, padx=10)
        # --- FIN DE LA MODIFICACIÓN ---
        
        def on_preset_change(selection):
            self.update_download_button_state()
            self._update_export_button_state()
            self.save_settings()
        
        self.recode_preset_menu = ctk.CTkOptionMenu(self.quick_recode_options_frame, values=["- Aún no disponible -"], command=on_preset_change)
        self.recode_preset_menu.pack(pady=10, padx=10, fill="x")

        # --- AÑADIR ESTAS LÍNEAS (TOOLTIP 10) ---
        preset_tooltip_text = "Perfiles pre-configurados para tareas comunes.\n\n• Puedes crear y guardar tus propios presets desde el 'Modo Manual'.\n• Tus presets guardados aparecerán en esta lista."
        Tooltip(preset_label, preset_tooltip_text, delay_ms=1000)
        Tooltip(self.recode_preset_menu, preset_tooltip_text, delay_ms=1000)
        
        preset_actions_frame = ctk.CTkFrame(self.quick_recode_options_frame, fg_color="transparent")
        preset_actions_frame.pack(fill="x", padx=10, pady=(0, 10))
        preset_actions_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.import_preset_button = ctk.CTkButton(
            preset_actions_frame,
            text="📥 Importar",
            command=self.import_preset_file,
            fg_color="#28A745",
            hover_color="#218838"
        )
        self.import_preset_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        self.export_preset_button = ctk.CTkButton(
            preset_actions_frame,
            text="📤 Exportar",
            command=self.export_preset_file,
            state="disabled",
            fg_color="#007BFF",
            hover_color="#0069D9"
        )
        self.export_preset_button.grid(row=0, column=1, padx=5, sticky="ew")
        
        self.delete_preset_button = ctk.CTkButton(
            preset_actions_frame,
            text="🗑️ Eliminar",
            command=self.delete_preset_file,
            state="disabled",
            fg_color="#DC3545",
            hover_color="#C82333"
        )
        self.delete_preset_button.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        
        self.keep_original_quick_checkbox = ctk.CTkCheckBox(
            self.recode_quick_frame, 
            text="Mantener los archivos originales",
            command=self.save_settings,
            state="disabled"
        )
        self.keep_original_quick_checkbox.pack(anchor="w", padx=10, pady=(0, 5))
        self.keep_original_quick_checkbox.select()
        

        self.recode_manual_frame = ctk.CTkFrame(self.recode_main_frame, fg_color="transparent")
        
        self.recode_toggle_frame = ctk.CTkFrame(self.recode_manual_frame, fg_color="transparent")
        self.recode_toggle_frame.pack(side="top", fill="x", padx=10, pady=(0, 10)) 
        self.recode_toggle_frame.grid_columnconfigure((0, 1), weight=1)

        self.recode_video_checkbox = ctk.CTkCheckBox(self.recode_toggle_frame, text="Recodificar Video", command=self._toggle_recode_panels, state="disabled")
        self.recode_video_checkbox.grid(row=0, column=0, padx=10, pady=(5, 5), sticky="w")

        # --- AÑADIR TOOLTIP VIDEO (TOOLTIP 11) ---
        video_recode_tooltip = "Re-codifica solo la pista de video pero copia el audio si 'Recodificar Audio' está desmarcado."
        Tooltip(self.recode_video_checkbox, video_recode_tooltip, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        self.recode_audio_checkbox = ctk.CTkCheckBox(self.recode_toggle_frame, text="Recodificar Audio", command=self._toggle_recode_panels, state="disabled")
        self.recode_audio_checkbox.grid(row=0, column=1, padx=10, pady=(5, 5), sticky="w")

        # --- AÑADIR TOOLTIP AUDIO (TOOLTIP 12) ---
        audio_recode_tooltip = "Re-codifica solo la pista de audio pero copia el video si 'Recodificar Video' está desmarcado."
        Tooltip(self.recode_audio_checkbox, audio_recode_tooltip, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        self.keep_original_checkbox = ctk.CTkCheckBox(self.recode_toggle_frame, text="Mantener los archivos originales", state="disabled", command=self.save_settings)
        self.keep_original_checkbox.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="w")

        self.keep_original_checkbox.select()
        
        self.recode_warning_frame = ctk.CTkFrame(self.recode_manual_frame, fg_color="transparent")
        self.recode_warning_frame.pack(pady=0, padx=0, fill="x")
        self.recode_warning_label = ctk.CTkLabel(self.recode_warning_frame, text="", wraplength=400, justify="left", font=ctk.CTkFont(weight="bold"))
        self.recode_warning_label.pack(pady=5, padx=5, fill="both", expand=True)
        
        self.recode_options_frame = ctk.CTkFrame(self.recode_manual_frame)
        ctk.CTkLabel(self.recode_options_frame, text="Opciones de Video", font=ctk.CTkFont(weight="bold")).pack(pady=(5, 10), padx=10)
        self.proc_type_var = ctk.StringVar(value="")

        proc_frame = ctk.CTkFrame(self.recode_options_frame, fg_color="transparent")
        proc_frame.pack(fill="x", padx=10, pady=5)
        self.cpu_radio = ctk.CTkRadioButton(proc_frame, text="CPU", variable=self.proc_type_var, value="CPU", command=self.update_codec_menu)
        self.cpu_radio.pack(side="left", padx=10)
        
        # --- AÑADIR TOOLTIP PARA CPU (TOOLTIP 8) ---
        cpu_tooltip_text = "Usa el procesador (CPU) para la recodificación.\nEs más lento que la GPU, pero ofrece la máxima calidad y compatibilidad con todos los códecs de software."
        Tooltip(self.cpu_radio, cpu_tooltip_text, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        self.gpu_radio = ctk.CTkRadioButton(proc_frame, text="GPU", variable=self.proc_type_var, value="GPU", state="disabled", command=self.update_codec_menu)
        self.gpu_radio.pack(side="left", padx=20)

        # --- AÑADIR TOOLTIP PARA GPU (TOOLTIP 9) ---
        gpu_tooltip_text = "Usa la tarjeta gráfica (GPU) para una recodificación acelerada por hardware (más rápida).\nSolo se listarán códecs compatibles con la GPU (ej: NVENC, AMF, QSV)."
        Tooltip(self.gpu_radio, gpu_tooltip_text, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        codec_options_frame = ctk.CTkFrame(self.recode_options_frame)

        codec_options_frame.pack(fill="x", padx=10, pady=5)
        codec_options_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(codec_options_frame, text="Codec:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.recode_codec_menu = ctk.CTkOptionMenu(codec_options_frame, values=["-"], state="disabled", command=self.update_profile_menu)
        self.recode_codec_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkLabel(codec_options_frame, text="Perfil/Calidad:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.recode_profile_menu = ctk.CTkOptionMenu(codec_options_frame, values=["-"], state="disabled", command=self.on_profile_selection_change) 
        self.recode_profile_menu.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.custom_bitrate_frame = ctk.CTkFrame(codec_options_frame, fg_color="transparent")
        ctk.CTkLabel(self.custom_bitrate_frame, text="Bitrate (Mbps):").pack(side="left", padx=(0, 5))
        self.custom_bitrate_entry = ctk.CTkEntry(self.custom_bitrate_frame, placeholder_text="Ej: 8", width=100)
        self.custom_bitrate_entry.bind("<KeyRelease>", self.update_download_button_state)
        self.custom_bitrate_entry.pack(side="left")
        self.custom_gif_frame = ctk.CTkFrame(codec_options_frame, fg_color="transparent")
        self.custom_gif_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5)
        self.custom_gif_frame.grid_remove() 
        ctk.CTkLabel(self.custom_gif_frame, text="FPS:").pack(side="left", padx=(0, 5))
        self.custom_gif_fps_entry = ctk.CTkEntry(self.custom_gif_frame, placeholder_text="15", width=60)
        self.custom_gif_fps_entry.pack(side="left")
        ctk.CTkLabel(self.custom_gif_frame, text="Ancho:").pack(side="left", padx=(15, 5))
        self.custom_gif_width_entry = ctk.CTkEntry(self.custom_gif_frame, placeholder_text="480", width=60)
        self.custom_gif_width_entry.pack(side="left")
        self.estimated_size_label = ctk.CTkLabel(self.custom_bitrate_frame, text="N/A", font=ctk.CTkFont(weight="bold"))
        self.estimated_size_label.pack(side="right", padx=(10, 0))
        ctk.CTkLabel(self.custom_bitrate_frame, text="Tamaño Estimado:").pack(side="right")
        ctk.CTkLabel(codec_options_frame, text="Contenedor:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        container_value_frame = ctk.CTkFrame(codec_options_frame, fg_color="transparent")
        container_value_frame.grid(row=3, column=1, padx=5, pady=0, sticky="ew")
        self.recode_container_label = ctk.CTkLabel(container_value_frame, text="-", font=ctk.CTkFont(weight="bold"))
        self.recode_container_label.pack(side="left", padx=5, pady=5)

        self.fps_frame = ctk.CTkFrame(self.recode_options_frame)
        self.fps_frame.pack(fill="x", padx=10, pady=(10, 5))
        self.fps_frame.grid_columnconfigure(1, weight=1)
        self.fps_checkbox = ctk.CTkCheckBox(self.fps_frame, text="Forzar FPS Constantes (CFR)", command=self.toggle_fps_entry_panel)
        self.fps_checkbox.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # --- AÑADIR ESTAS LÍNEAS (TOOLTIP 14) ---
        fps_tooltip_text = "Fuerza una tasa de fotogramas constante (CFR).\n\nMuchos videos de internet usan FPS Variable (VFR), lo que causa problemas de audio desincronizado en editores como Premiere o After Effects. Activando esto se soluciona."
        Tooltip(self.fps_checkbox, fps_tooltip_text, delay_ms=1000)
        # --- FIN DEL TOOLTIP ---

        self.fps_value_label = ctk.CTkLabel(self.fps_frame, text="Valor FPS:")

        self.fps_entry = ctk.CTkEntry(self.fps_frame, placeholder_text="Ej: 23.976, 25, 29.97, 30, 60")
        self.toggle_fps_entry_panel()
        self.resolution_frame = ctk.CTkFrame(self.recode_options_frame)
        self.resolution_frame.pack(fill="x", padx=10, pady=5)
        self.resolution_frame.grid_columnconfigure(1, weight=1)
        self.resolution_checkbox = ctk.CTkCheckBox(self.resolution_frame, text="Cambiar Resolución", command=self.toggle_resolution_panel)
        self.resolution_checkbox.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        self.resolution_options_frame = ctk.CTkFrame(self.resolution_frame, fg_color="transparent")
        self.resolution_options_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.resolution_options_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.resolution_options_frame, text="Preset:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.resolution_preset_menu = ctk.CTkOptionMenu(self.resolution_options_frame, values=["Personalizado", "4K UHD", "2K QHD", "1080p Full HD", "720p HD", "480p SD"], command=self.on_resolution_preset_change)
        self.resolution_preset_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.resolution_manual_frame = ctk.CTkFrame(self.resolution_options_frame, fg_color="transparent")
        self.resolution_manual_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.resolution_manual_frame.grid_columnconfigure((0, 2), weight=1)
        ctk.CTkLabel(self.resolution_manual_frame, text="Ancho:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.width_entry = ctk.CTkEntry(self.resolution_manual_frame, width=80)
        self.width_entry.grid(row=0, column=1, padx=5, pady=5)
        self.width_entry.bind("<KeyRelease>", lambda event: self.on_dimension_change("width"))
        self.aspect_ratio_lock = ctk.CTkCheckBox(self.resolution_manual_frame, text="🔗", font=ctk.CTkFont(size=16), command=self.on_aspect_lock_change)
        self.aspect_ratio_lock.grid(row=0, column=2, padx=5, pady=5)
        ctk.CTkLabel(self.resolution_manual_frame, text="Alto:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.height_entry = ctk.CTkEntry(self.resolution_manual_frame, width=80)
        self.height_entry.grid(row=1, column=1, padx=5, pady=5)
        self.height_entry.bind("<KeyRelease>", lambda event: self.on_dimension_change("height"))
        self.no_upscaling_checkbox = ctk.CTkCheckBox(self.resolution_manual_frame, text="No ampliar resolución")
        self.no_upscaling_checkbox.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="w")
        self.toggle_resolution_panel()
        
        self.recode_audio_options_frame = ctk.CTkFrame(self.recode_manual_frame)
        self.recode_audio_options_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.recode_audio_options_frame, text="Opciones de Audio", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(5, 10), padx=10)
        ctk.CTkLabel(self.recode_audio_options_frame, text="Codec de Audio:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.recode_audio_codec_menu = ctk.CTkOptionMenu(self.recode_audio_options_frame, values=["-"], state="disabled", command=self.update_audio_profile_menu)
        self.recode_audio_codec_menu.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkLabel(self.recode_audio_options_frame, text="Perfil de Audio:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.recode_audio_profile_menu = ctk.CTkOptionMenu(self.recode_audio_options_frame, values=["-"], state="disabled", command=lambda _: self._validate_recode_compatibility())
        self.recode_audio_profile_menu.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        self.save_preset_frame = ctk.CTkFrame(self.recode_manual_frame)
        self.save_preset_frame.pack(side="bottom", fill="x", padx=0, pady=(10, 0))
        
        self.save_preset_button = ctk.CTkButton(
            self.save_preset_frame, 
            text="Guardar como ajuste prestablecido",
            command=self.open_save_preset_dialog
        )
        self.save_preset_button.pack(fill="x", padx=10, pady=(10, 5))
        
        self.recode_extract_frame = ctk.CTkFrame(self.recode_main_frame, fg_color="transparent")

        # --- NUEVA UI DE EXTRACCIÓN ---
        self.extract_options_frame = ctk.CTkFrame(self.recode_extract_frame)
        self.extract_options_frame.pack(fill="x", padx=10, pady=5)
        self.extract_options_frame.grid_columnconfigure(1, weight=1)

        # 🆕 0. Checkbox "Mantener original" (PRIMERO, como en otros modos)
        self.keep_original_extract_checkbox = ctk.CTkCheckBox(
            self.extract_options_frame, 
            text="Mantener el video original",
            command=self.save_settings
        )
        self.keep_original_extract_checkbox.grid(row=0, column=0, columnspan=2, padx=10, pady=(5, 10), sticky="w")
        self.keep_original_extract_checkbox.select()  # Seleccionado por defecto

        # 1. Tipo de Extracción
        ctk.CTkLabel(self.extract_options_frame, text="Tipo:").grid(row=1, column=0, padx=(10, 5), pady=5, sticky="w")
        self.extract_type_menu = ctk.CTkOptionMenu(
            self.extract_options_frame,
            values=["Video a Secuencia de Imágenes"],
            state="disabled" # Por ahora solo hay 1 opción
        )
        self.extract_type_menu.grid(row=1, column=1, padx=(0, 10), pady=5, sticky="ew")

        # 2. Formato de Imagen
        ctk.CTkLabel(self.extract_options_frame, text="Formato:").grid(row=2, column=0, padx=(10, 5), pady=5, sticky="w")
        self.extract_format_menu = ctk.CTkOptionMenu(
            self.extract_options_frame,
            values=["PNG (calidad alta)", "JPG (tamaño reducido)"],
            command=self._toggle_extract_options
        )
        self.extract_format_menu.grid(row=2, column=1, padx=(0, 10), pady=5, sticky="ew")

        # 3. Opciones de Calidad JPG (ocultas por defecto)
        self.extract_jpg_quality_frame = ctk.CTkFrame(self.extract_options_frame, fg_color="transparent")
        self.extract_jpg_quality_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.extract_jpg_quality_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.extract_jpg_quality_frame, text="Calidad JPG (1-5):").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.extract_jpg_quality_entry = ctk.CTkEntry(self.extract_jpg_quality_frame, placeholder_text="2 (Muy Alta)")
        self.extract_jpg_quality_entry.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="ew")
        Tooltip(self.extract_jpg_quality_entry, "Calidad de FFmpeg (-q:v). Rango: 1 (mejor) a 31 (peor). Se recomienda 2-5.", delay_ms=1000)
        self.extract_jpg_quality_frame.grid_forget()

        # 4. FPS
        ctk.CTkLabel(self.extract_options_frame, text="FPS:").grid(row=4, column=0, padx=(10, 5), pady=5, sticky="w")
        self.extract_fps_entry = ctk.CTkEntry(self.extract_options_frame, placeholder_text="Vacío = Todos los fotogramas")
        self.extract_fps_entry.grid(row=4, column=1, padx=(0, 10), pady=5, sticky="ew")
        Tooltip(self.extract_fps_entry, "Ej: '10' para 10 FPS.\nDéjalo vacío para extraer CADA fotograma (¡puede generar miles de archivos!)", delay_ms=1000)

        # 5. Nombre de la carpeta de salida
        ctk.CTkLabel(self.extract_options_frame, text="Nombre de carpeta:").grid(row=5, column=0, padx=(10, 5), pady=5, sticky="w")
        self.extract_folder_name_entry = ctk.CTkEntry(self.extract_options_frame, placeholder_text="Nombre del video + '_frames'")
        self.extract_folder_name_entry.grid(row=5, column=1, padx=(0, 10), pady=5, sticky="ew")
        Tooltip(self.extract_folder_name_entry, "Personaliza el nombre de la carpeta donde se guardarán las imágenes.\nSi lo dejas vacío, se usará el nombre del video.", delay_ms=1000)

        # 6. Frame de resultados (SIEMPRE VISIBLE)
        self.extract_results_frame = ctk.CTkFrame(self.extract_options_frame, fg_color="transparent")
        self.extract_results_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(15, 5))
        self.extract_results_frame.grid_columnconfigure(0, weight=1)

        # Etiqueta de éxito (inicialmente con texto vacío)
        self.extract_success_label = ctk.CTkLabel(
            self.extract_results_frame, 
            text="",  # ✅ Vacío por defecto
            font=ctk.CTkFont(weight="bold"),
            text_color="#28A745"
        )
        self.extract_success_label.grid(row=0, column=0, pady=(5, 10), sticky="ew")

        # Botón para enviar a Herramientas de Imagen - SIEMPRE VISIBLE
        self.send_to_imagetools_button = ctk.CTkButton(
            self.extract_results_frame,
            text="Enviar a Herramientas de Imagen",
            command=self._send_folder_to_image_tools,
            height=32,
            state="disabled"  # ✅ Deshabilitado por defecto
        )
        self.send_to_imagetools_button.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")
        # --- FIN DE LA NUEVA UI DE EXTRACCIÓN ---

        local_import_frame = ctk.CTkFrame(self.recode_main_frame)
        local_import_frame.pack(side="bottom", fill="x", padx=10, pady=(15, 5))
        ctk.CTkLabel(local_import_frame, text="¿Tienes un archivo existente?", font=ctk.CTkFont(weight="bold")).pack()
        self.import_button = ctk.CTkButton(local_import_frame, text="Importar Archivo Local para Recodificar", command=self.import_local_file)
        self.import_button.pack(fill="x", padx=10, pady=5)
        self.save_in_same_folder_check = ctk.CTkCheckBox(local_import_frame, text="Guardar en la misma carpeta que el original", command=self._on_save_in_same_folder_change)
        self.clear_local_file_button = ctk.CTkButton(local_import_frame, text="Limpiar y Volver a Modo URL", fg_color="gray", hover_color="#555555", command=self.reset_to_url_mode)
        
        # 1. Panel de Progreso (Lo creamos PRIMERO para que quede al fondo absoluto)
        progress_frame = ctk.CTkFrame(self)
        progress_frame.pack(side="bottom", pady=(0, 10), padx=10, fill="x") # <--- side="bottom"

        self.progress_label = ctk.CTkLabel(progress_frame, text="Esperando...")
        self.progress_label.pack(pady=(5,0))
        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0,5), padx=10, fill="x")

        # 2. Panel de Descarga (Lo creamos SEGUNDO, quedará encima del progreso)
        download_frame = ctk.CTkFrame(self)
        download_frame.pack(side="bottom", pady=10, padx=10, fill="x") # <--- side="bottom"

        ctk.CTkLabel(download_frame, text="Carpeta de Salida:").pack(side="left", padx=(10, 5))
        
        self.output_path_entry = ctk.CTkEntry(download_frame, placeholder_text="Selecciona una carpeta...")
        self.output_path_entry.bind("<KeyRelease>", self.update_download_button_state)
        self.output_path_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.output_path_entry))
        self.output_path_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        self.select_folder_button = ctk.CTkButton(download_frame, text="...", width=40, command=lambda: self.select_output_folder())
        self.select_folder_button.pack(side="left", padx=(0, 5))
        
        self.open_folder_button = ctk.CTkButton(download_frame, text="📂", width=40, font=ctk.CTkFont(size=16), command=self.open_last_download_folder, state="disabled")
        self.open_folder_button.pack(side="left", padx=(0, 5))

        # Etiquetas y Tooltips
        speed_label = ctk.CTkLabel(download_frame, text="Límite (MB/s):")
        speed_label.pack(side="left", padx=(10, 5))
        
        self.speed_limit_entry = ctk.CTkEntry(download_frame, width=50)
        
        tooltip_text = "Limita la velocidad de descarga (en MB/s).\nÚtil si las descargas fallan por 'demasiadas peticiones'."
        Tooltip(speed_label, tooltip_text, delay_ms=1000)
        Tooltip(self.speed_limit_entry, tooltip_text, delay_ms=1000)
        
        self.speed_limit_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.speed_limit_entry))
        self.speed_limit_entry.pack(side="left", padx=(0, 10))

        self.download_button = ctk.CTkButton(
            download_frame, 
            text=self.original_download_text, 
            state="disabled", 
            command=self.original_download_command, 
            fg_color=self.DOWNLOAD_BTN_COLOR, 
            hover_color=self.DOWNLOAD_BTN_HOVER,
            text_color_disabled=self.DISABLED_TEXT_COLOR
        )
        self.download_button.pack(side="left", padx=(5, 10))

        # 3. FINALMENTE: Empaquetar el panel central (info_frame)
        # Esto le dice a la app: "Usa TODO el espacio que sobre para el panel de en medio"
        # Asegúrate de haber guardado 'self.info_frame_ref' al inicio de la función como te indiqué antes.
        if hasattr(self, 'info_frame_ref'):
            self.info_frame_ref.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        
        # --- Binds y Configuración Final ---
        self.on_mode_change(self.mode_selector.get())
        self.on_profile_selection_change(self.recode_profile_menu.get())
        self.start_h.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.start_h, self.start_m), self.update_download_button_state()))
        self.start_m.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.start_m, self.start_s), self.update_download_button_state()))
        self.start_s.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.start_s), self.update_download_button_state()))
        self.end_h.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.end_h, self.end_m), self.update_download_button_state()))
        self.end_m.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.end_m, self.end_s), self.update_download_button_state()))
        self.end_s.bind("<KeyRelease>", lambda e: (self._handle_time_input(e, self.end_s), self.update_download_button_state()))
        self._toggle_fragment_panel()
        self.recode_mode_selector.set("Modo Rápido")
        self._on_recode_mode_change("Modo Rápido")
        
        self.recode_main_frame.pack(pady=(10, 0), padx=5, fill="both", expand=True)
        print("DEBUG: Panel de recodificación inicializado y visible")

    def create_entry_context_menu(self, widget):
        """Crea y muestra un menú contextual para un widget de entrada de texto."""
        menu = tkinter.Menu(self, tearoff=0)
        
        def copy_text():
            """Copia el texto seleccionado al portapapeles."""
            try:
                selected_text = widget.selection_get()
                if selected_text:
                    widget.clipboard_clear()
                    widget.clipboard_append(selected_text)
            except Exception:
                pass # No había nada seleccionado

        def cut_text():
            """Corta el texto seleccionado (copia y borra)."""
            try:
                selected_text = widget.selection_get()
                if selected_text:
                    # 1. Copiar al portapapeles
                    widget.clipboard_clear()
                    widget.clipboard_append(selected_text)
                    # 2. Borrar selección
                    widget.delete("sel.first", "sel.last")
                    self.app.after(10, self.update_download_button_state)
            except Exception:
                pass # No había nada seleccionado

        def paste_text():
            """Pega el texto del portapapeles."""
            try:
                # 1. Borrar selección actual (si existe)
                if widget.selection_get():
                    widget.delete("sel.first", "sel.last")
            except Exception:
                pass # No había nada seleccionado

            try:
                # 2. Pegar desde el portapapeles
                widget.insert("insert", self.clipboard_get())
                self.app.after(10, self.update_download_button_state)
            except tkinter.TclError:
                pass # Portapapeles vacío

        menu.add_command(label="Cortar", command=cut_text)
        menu.add_command(label="Copiar", command=copy_text)
        menu.add_command(label="Pegar", command=paste_text)
        menu.add_separator()
        menu.add_command(label="Seleccionar todo", command=lambda: widget.select_range(0, 'end'))
        menu.tk_popup(widget.winfo_pointerx(), widget.winfo_pointery())
        
    def paste_into_widget(self, widget):
        """Obtiene el contenido del portapapeles y lo inserta en un widget."""
        try:
            clipboard_text = self.clipboard_get()
            widget.insert('insert', clipboard_text)
        except tkinter.TclError:
            pass
        

    def _open_release_page(self):
        """Abre la página de la release en el navegador."""
        if self.release_page_url:
            webbrowser.open_new_tab(self.release_page_url)
        else:
            from src.core.setup import check_app_update
            self.app_status_label.configure(text=f"DowP v{self.APP_VERSION} - Verificando de nuevo...")
            self.update_app_button.configure(state="disabled")
            threading.Thread(
                target=lambda: self.app.on_update_check_complete(check_app_update(self.app.APP_VERSION)),
                daemon=True
            ).start()

    def update_setup_download_progress(self, source, text, value):
        """
        Callback para actualizar el estado de descarga de UNA dependencia (FFmpeg o Deno).
        'source' debe ser 'ffmpeg' o 'deno'.
        'value' está en el rango 0-100.
        """
        if source not in self.active_downloads_state:
            return

        # Normalizar valor a 0.0 - 1.0
        progress_value = float(value) / 100.0

        self.active_downloads_state[source]["text"] = text
        self.active_downloads_state[source]["value"] = progress_value
        # Un valor entre 0 y 1 (excluyentes) significa que está activamente descargando
        self.active_downloads_state[source]["active"] = (progress_value > 0 and progress_value < 1)

        # Llamar al renderizador
        self._render_setup_progress()

    def _render_setup_progress(self):
        ffmpeg_state = self.active_downloads_state["ffmpeg"]
        deno_state = self.active_downloads_state["deno"]
        poppler_state = self.active_downloads_state.get("poppler", {"text": "", "value": 0.0, "active": False})
        inkscape_state = self.active_downloads_state.get("inkscape", {"text": "", "value": 0.0, "active": False})
        rembg_state = self.active_downloads_state.get("rembg", {"text": "", "value": 0.0, "active": False}) # <--- NUEVO

        # Sumar rembg al conteo
        active_count = sum([
            ffmpeg_state["active"], deno_state["active"], 
            poppler_state["active"], inkscape_state["active"], 
            rembg_state["active"]
        ])
        
        final_text = "Esperando..."
        final_progress = 0.0

        if active_count > 0:
            final_text = f"Descargando dependencias ({active_count} activas)..."
            # Sumar rembg al promedio
            total_val = (ffmpeg_state["value"] + deno_state["value"] + 
                         poppler_state["value"] + inkscape_state["value"] + 
                         rembg_state["value"])
            
            final_progress = total_val / max(1, active_count)
            
            if active_count == 1:
                if ffmpeg_state["active"]: final_text = ffmpeg_state["text"]; final_progress = ffmpeg_state["value"]
                elif deno_state["active"]: final_text = deno_state["text"]; final_progress = deno_state["value"]
                elif poppler_state["active"]: final_text = poppler_state["text"]; final_progress = poppler_state["value"]
                elif inkscape_state["active"]: final_text = inkscape_state["text"]; final_progress = inkscape_state["value"]
                elif rembg_state["active"]: final_text = rembg_state["text"]; final_progress = rembg_state["value"] # <--- NUEVO
        else:
            # Mostrar último mensaje relevante
            if rembg_state["text"]: final_text = rembg_state["text"]; final_progress = rembg_state["value"] # <--- NUEVO
            elif poppler_state["text"]: final_text = poppler_state["text"]; final_progress = poppler_state["value"]
            elif deno_state["text"]: final_text = deno_state["text"]; final_progress = deno_state["value"]
            elif ffmpeg_state["text"]: final_text = ffmpeg_state["text"]; final_progress = ffmpeg_state["value"]
            elif inkscape_state["text"]: final_text = inkscape_state["text"]; final_progress = inkscape_state["value"]
            
        self.update_progress(final_progress, final_text)

    def _execute_fragment_clipping(self, input_filepath, start_time, end_time):
        """
        Corta un fragmento de un archivo de video/audio usando FFmpeg en modo de copia de stream.
        
        🆕 NUEVO: Ahora interpreta correctamente:
        - Solo inicio → Desde ese tiempo hasta el final
        - Solo fin → Desde el principio hasta ese tiempo
        - Ambos → Fragmento específico
        
        Args:
            input_filepath (str): La ruta al archivo de medios original.
            start_time (str): El tiempo de inicio del corte (formato HH:MM:SS o vacío).
            end_time (str): El tiempo de finalización del corte (formato HH:MM:SS o vacío).
            
        Returns:
            str: La ruta al archivo de medios recién creado y cortado.
        
        Raises:
            UserCancelledError: Si la operación es cancelada por el usuario.
            Exception: Si FFmpeg falla durante el proceso de corte.
        """
        self.app.after(0, self.update_progress, 98, "Cortando fragmento con ffmpeg...")
        
        base_name, ext = os.path.splitext(os.path.basename(input_filepath))
        clipped_filename = f"{base_name}_fragmento{ext}"
        desired_clipped_filepath = os.path.join(os.path.dirname(input_filepath), clipped_filename)

        clipped_filepath, backup_path = self._resolve_output_path(desired_clipped_filepath)

        # 🆕 CÁLCULO INTELIGENTE DE DURACIÓN
        # Si no hay start_time, asumir 0
        start_seconds = self.time_str_to_seconds(start_time) if start_time else 0
        
        # Si no hay end_time, usar la duración completa del video
        if end_time:
            end_seconds = self.time_str_to_seconds(end_time)
        else:
            end_seconds = self.video_duration
        
        # Duración real del fragmento
        fragment_duration = end_seconds - start_seconds
        
        if fragment_duration <= 0:
            raise Exception("La duración del fragmento es inválida (tiempo final debe ser mayor que inicial)")

        pre_params = []
        ffmpeg_params = []
        
        # -ss va ANTES de -i para búsqueda rápida (solo si hay tiempo de inicio)
        if start_time:
            pre_params.extend(['-ss', start_time])
        
        # Usar -t (duración) para especificar cuánto cortar desde el punto de inicio
        duration_str = self._seconds_to_time_str(fragment_duration)
        ffmpeg_params.extend(['-t', duration_str])

        # Usamos 'copy' para un corte rápido y sin recodificar
        ffmpeg_params.extend(['-c:v', 'copy', '-c:a', 'copy', '-map', '0:v?', '-map', '0:a?'])
        
        clip_opts = {
            "input_file": input_filepath,
            "output_file": clipped_filepath,
            "ffmpeg_params": ffmpeg_params,
            "pre_params": pre_params,
            "duration": fragment_duration
        }
        
        # Ejecuta el comando de corte a través del procesador de FFmpeg
        self.ffmpeg_processor.execute_recode(clip_opts, 
                                            lambda p, m: self.update_progress(p, f"Cortando... {p:.1f}%"), 
                                            self.cancellation_event)
        
        # Limpia el backup si se creó uno
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError as e:
                print(f"ADVERTENCIA: No se pudo limpiar el backup del recorte: {e}")

        return clipped_filepath
        
    def _seconds_to_time_str(self, seconds):
        """Convierte segundos a formato HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _handle_optional_clipping(self, downloaded_filepath, options):
        """
        Verifica si se necesita un recorte y lo ejecuta.
        Maneja la eliminación del archivo original si es necesario.
        
        🆕 NUEVO: Ahora verifica si el archivo ya fue cortado por yt-dlp
        
        Args:
            downloaded_filepath (str): La ruta al archivo recién descargado.
            options (dict): El diccionario de opciones de la operación.
            
        Returns:
            str: La ruta final al archivo que debe ser procesado (ya sea el original o el fragmento).
        """
        # Verificar si el usuario QUERÍA un fragmento
        user_wanted_fragment = options.get("fragment_enabled") and (options.get("start_time") or options.get("end_time"))
        
        if not user_wanted_fragment:
            return downloaded_filepath

        # Lógica de detección:
        # 1. Si "force_full_download" estaba ON, yt-dlp bajó todo → NECESITAMOS CORTAR.
        # 2. Si "fragment_enabled" sigue siendo True, significa que yt-dlp NO lo cortó (o forzamos full) → NECESITAMOS CORTAR.
        # 3. Si "fragment_enabled" fue puesto a False en _perform_download, ya está cortado.

        if options.get("force_full_download"):
            print("DEBUG: 🎬 Video completo descargado por solicitud (Modo Rápido). Cortando localmente...")
        
        elif not options.get("fragment_enabled"):
            # Esta bandera se apaga en _perform_download si yt-dlp tuvo éxito nativo
            print("DEBUG: ✅ El fragmento ya fue descargado directamente por yt-dlp. Saltando corte local.")
            return downloaded_filepath

        # Si llegamos aquí, necesitamos cortar con FFmpeg
        print("DEBUG: ✂️ Iniciando corte local con FFmpeg...")
        clipped_filepath = self._execute_fragment_clipping(
            input_filepath=downloaded_filepath,
            start_time=options.get("start_time"),
            end_time=options.get("end_time")
        )
        
        # Después del corte, limpiamos las opciones para evitar el doble recorte.
        options["fragment_enabled"] = False
        options["start_time"] = ""
        options["end_time"] = ""
        
        # Manejo del archivo original (Borrar o Renombrar a _full)
        try:
            if options.get("keep_original_on_clip"):
                # Lógica para conservar: Renombrar agregando _full
                directory = os.path.dirname(downloaded_filepath)
                filename = os.path.basename(downloaded_filepath)
                name, ext = os.path.splitext(filename)
                
                # Crear nombre nuevo: video_full.mp4
                new_full_name = f"{name}_full{ext}"
                new_full_path = os.path.join(directory, new_full_name)
                
                # Renombrar (si ya existe uno igual, lo sobrescribe o falla según el SO, idealmente validar antes)
                if os.path.exists(new_full_path):
                    try: os.remove(new_full_path)
                    except: pass
                
                os.rename(downloaded_filepath, new_full_path)
                print(f"DEBUG: Archivo original conservado como: {new_full_path}")
                
            else:
                # Lógica normal: Borrar el original
                os.remove(downloaded_filepath)
                print(f"DEBUG: Archivo original completo eliminado tras el recorte: {downloaded_filepath}")
                
        except OSError as err:
            print(f"ADVERTENCIA: Error gestionando el archivo original tras el recorte: {err}")
            
        # Devolvemos la ruta al nuevo fragmento (esto es lo que se mostrará en la UI como "Completado")
        return clipped_filepath

    def _on_recode_mode_change(self, mode):
        """Muestra el panel de recodificación apropiado."""
        
        # Ocultar todos los paneles primero
        self.recode_quick_frame.pack_forget()
        self.recode_manual_frame.pack_forget()
        self.save_preset_frame.pack_forget()
        if hasattr(self, 'recode_extract_frame'):
            self.recode_extract_frame.pack_forget()

        # Mostrar el panel correcto
        if mode == "Modo Rápido":
            self.recode_quick_frame.pack(side="top", fill="x", padx=10, pady=0)
        
        elif mode == "Modo Manual":
            self.recode_manual_frame.pack(side="top", fill="x", padx=0, pady=0)
        
        elif mode == "Modo Extraer":
            self.recode_extract_frame.pack(side="top", fill="x", padx=10, pady=0)
        
        self._validate_recode_compatibility()
        self._update_save_preset_visibility()

    def _on_quick_recode_toggle(self):
        """
        Muestra/oculta las opciones de recodificación en Modo Rápido
        según si el checkbox está marcado
        """
        if self.apply_quick_preset_checkbox.get() == 1:
            
            self.quick_recode_options_frame.pack(fill="x", padx=0, pady=0)
            
            # --- INICIO DE CORRECCIÓN ---
            # Comprobar si estamos en modo local ANTES de habilitar la casilla
            if not self.local_file_path:
                self.keep_original_quick_checkbox.configure(state="normal")
            else:
                # Si es modo local, forzar la selección y deshabilitarla
                self.keep_original_quick_checkbox.select()
                self.keep_original_quick_checkbox.configure(state="disabled")
            # --- FIN DE CORRECCIÓN ---
            
        else:
            
            self.quick_recode_options_frame.pack_forget()
            self.keep_original_quick_checkbox.configure(state="disabled")
        
        self.update_download_button_state()
        self.save_settings()
        
    def _populate_preset_menu(self):
        """
        Lee los presets disponibles y los añade al menú desplegable del Modo Rápido,
        filtrando por el modo principal seleccionado (Video+Audio vs Solo Audio).
        """
        current_main_mode = self.mode_selector.get()
        compatible_presets = []

        for name, data in self.built_in_presets.items():
            if data.get("mode_compatibility") == current_main_mode:
                compatible_presets.append(name)
        
        custom_presets_found = False
        for preset in getattr(self, "custom_presets", []):
            if preset.get("data", {}).get("mode_compatibility") == current_main_mode:
                if not custom_presets_found:
                    if compatible_presets:
                        compatible_presets.append("--- Mis Presets ---")
                    custom_presets_found = True
                compatible_presets.append(preset.get("name"))

        if compatible_presets:
            self.recode_preset_menu.configure(values=compatible_presets, state="normal")
            
            saved_preset = self.app.quick_preset_saved
            if saved_preset and saved_preset in compatible_presets:
                self.recode_preset_menu.set(saved_preset)
            else:
                self.recode_preset_menu.set(compatible_presets[0])
                
            self._update_export_button_state()
        else:
            self.recode_preset_menu.configure(values=["- No hay presets para este modo -"], state="disabled")
            self.recode_preset_menu.set("- No hay presets para este modo -")
            self.export_preset_button.configure(state="disabled")

    def _update_export_button_state(self):
        """
        Habilita/desahabilita los botones de exportar y eliminar según si el preset es personalizado
        """
        selected_preset = self.recode_preset_menu.get()
        
        is_custom = any(p["name"] == selected_preset for p in self.custom_presets)
        
        if is_custom:
            self.export_preset_button.configure(state="normal")
            self.delete_preset_button.configure(state="normal")
        else:
            self.export_preset_button.configure(state="disabled")
            self.delete_preset_button.configure(state="disabled")

    def _find_preset_params(self, preset_name):
        """
        Busca un preset por su nombre, primero en los personalizados y luego en los integrados.
        Devuelve el diccionario de parámetros si lo encuentra.
        """
        for preset in getattr(self, 'custom_presets', []):
            if preset.get("name") == preset_name:
                return preset.get("data", {})
        
        if preset_name in self.built_in_presets:  
            return self.built_in_presets[preset_name]
            
        return {}

    def time_str_to_seconds(self, time_str):
        """Convierte un string HH:MM:SS a segundos."""
        if not time_str: 
            return None
        parts = time_str.split(':')
        seconds = 0
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            seconds = int(parts[0])
        return seconds

    def _get_compatible_audio_codecs(self, target_container):
        """
        Devuelve una lista de nombres de códecs de audio amigables que son
        compatibles con un contenedor específico.
        """
        all_audio_codecs = self.ffmpeg_processor.available_encoders.get("CPU", {}).get("Audio", {})
        if not target_container or target_container == "-":
            return list(all_audio_codecs.keys()) or ["-"]
        rules = self.app.COMPATIBILITY_RULES.get(target_container, {})
        allowed_ffmpeg_codecs = rules.get("audio", [])
        
        compatible_friendly_names = []

        for friendly_name, details in all_audio_codecs.items():
            ffmpeg_codec_name = next((key for key in details if key != 'container'), None)
            if ffmpeg_codec_name in allowed_ffmpeg_codecs:
                compatible_friendly_names.append(friendly_name)
        return compatible_friendly_names if compatible_friendly_names else ["-"]

    def _toggle_fragment_panel(self):
        """Muestra u oculta las opciones para cortar fragmentos."""
        if self.fragment_checkbox.get() == 1:
            self.fragment_options_frame.pack(fill="x", padx=10, pady=(0,5))
        else:
            self.fragment_options_frame.pack_forget()

    # --- NUEVOS MÉTODOS DE EXCLUSIVIDAD CON BLOQUEO VISUAL ---
    def _on_precise_clip_toggle(self):
        """
        Si se activa Corte Preciso: Desactiva y bloquea Descarga Completa.
        Si se desactiva: Desbloquea Descarga Completa.
        """
        if self.precise_clip_check.get() == 1:
            self.force_full_download_check.deselect()
            self.force_full_download_check.configure(state="disabled")
        else:
            self.force_full_download_check.configure(state="normal")

    def _on_force_full_download_toggle(self):
        """
        Si se activa Descarga Completa: Desactiva y bloquea Corte Preciso.
        Si se desactiva: Desbloquea Corte Preciso.
        """
        if self.force_full_download_check.get() == 1:
            self.precise_clip_check.deselect()
            self.precise_clip_check.configure(state="disabled")
        else:
            self.precise_clip_check.configure(state="normal")

    def _on_keep_original_clip_toggle(self):
        """
        Si se activa Conservar Completo:
        - Desactiva y bloquea 'Corte Preciso' y 'Descarga Completa'.
        Si se desactiva:
        - Desbloquea ambas opciones para que el usuario elija.
        """
        if self.keep_original_on_clip_check.get() == 1:
            # Bloquear y desmarcar "Corte Preciso"
            self.precise_clip_check.deselect()
            self.precise_clip_check.configure(state="disabled")

            # Bloquear y desmarcar "Descarga Completa"
            self.force_full_download_check.deselect()
            self.force_full_download_check.configure(state="disabled")
        else:
            # Desbloquear ambos (volver a estado normal)
            self.precise_clip_check.configure(state="normal")
            self.force_full_download_check.configure(state="normal")    

    def _handle_time_input(self, event, widget, next_widget=None):
        """Valida la entrada de tiempo y salta al siguiente campo."""
        text = widget.get()
        cleaned_text = "".join(filter(str.isdigit, text))
        final_text = cleaned_text[:2]
        if text != final_text:
            widget.delete(0, "end")
            widget.insert(0, final_text)
        if len(final_text) == 2 and next_widget:
            next_widget.focus()
            next_widget.select_range(0, 'end')

    def _get_formatted_time(self, h_widget, m_widget, s_widget):
        """
        Lee los campos de tiempo segmentados y los formatea como HH:MM:SS.
        NUEVO: Retorna "" si todos los campos están vacíos (se interpreta como "sin límite").
        """
        h = h_widget.get().strip()
        m = m_widget.get().strip()
        s = s_widget.get().strip()
        
        # Si todos los campos están vacíos, retornar string vacío
        if not h and not m and not s:
            return ""
        
        # Si algún campo tiene valor, rellenar con ceros
        h = h.zfill(2) if h else "00"
        m = m.zfill(2) if m else "00"
        s = s.zfill(2) if s else "00"
        
        return f"{h}:{m}:{s}"

    def _clean_ansi_codes(self, text):
        """Elimina los códigos de escape ANSI (colores) del texto."""
        if not text:
            return ""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def import_local_file(self):
        self.reset_to_url_mode()
        filetypes = [
            ("Archivos de Video", "*.mp4 *.mkv *.mov *.avi *.webm"),
            ("Archivos de Audio", "*.mp3 *.wav *.m4a *.flac *.opus"),
            ("Todos los archivos", "*.*")
        ]
        filepath = filedialog.askopenfilename(title="Selecciona un archivo para recodificar", filetypes=filetypes)
        self.app.lift()
        self.app.focus_force()
        if filepath:
            self.auto_save_thumbnail_check.pack_forget()
            self.cancellation_event.clear()
            self.progress_label.configure(text=f"Analizando archivo local: {os.path.basename(filepath)}...")
            self.progress_bar.start()
            self.open_folder_button.configure(state="disabled")
            threading.Thread(target=self._process_local_file_info, args=(filepath,), daemon=True).start()

    # ==========================================
    # ✅ NUEVA FUNCIÓN: API Pública para importar
    # ==========================================
    def import_local_file_from_path(self, filepath):
        """
        Importa un archivo local directamente sin abrir diálogo.
        Usado por la integración con Adobe.
        """
        if not os.path.exists(filepath):
            return

        # 1. Preparar la UI (limpiar modo URL)
        self.reset_to_url_mode()
        
        # 2. Configurar estado visual
        self.auto_save_thumbnail_check.pack_forget()
        self.cancellation_event.clear()
        self.progress_label.configure(text=f"Analizando archivo local: {os.path.basename(filepath)}...")
        self.progress_bar.start()
        self.open_folder_button.configure(state="disabled")
        
        # 3. Iniciar análisis en hilo
        threading.Thread(target=self._process_local_file_info, args=(filepath,), daemon=True).start()

    def _process_local_file_info(self, filepath):
        info = self.ffmpeg_processor.get_local_media_info(filepath)

        def update_ui():
            self.keep_original_on_clip_check.configure(state="disabled")
            self.progress_bar.stop()
            if not info:
                self.progress_label.configure(text="Error: No se pudo analizar el archivo.")
                self.progress_bar.set(0)
                return
            self.reset_ui_for_local_file()
            self.local_file_path = filepath
            self.keep_original_checkbox.select()
            self.keep_original_checkbox.configure(state="disabled")

            self.keep_original_quick_checkbox.select()
            self.keep_original_quick_checkbox.configure(state="disabled")

            # --- NUEVO: Deshabilitar estrategias de descarga en modo local ---
            self.precise_clip_check.deselect()
            self.precise_clip_check.configure(state="disabled")
            
            self.force_full_download_check.deselect()
            self.force_full_download_check.configure(state="disabled")

            # 🆕 También deshabilitar en modo extraer
            if hasattr(self, 'keep_original_extract_checkbox'):
                self.keep_original_extract_checkbox.select()
                self.keep_original_extract_checkbox.configure(state="disabled")

            self.recode_main_frame._parent_canvas.yview_moveto(0)
            self.save_in_same_folder_check.pack(padx=10, pady=(5,0), anchor="w")
            self.save_in_same_folder_check.select()
            video_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
            audio_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), None)
            if video_stream:
                self.original_video_width = video_stream.get('width', 0)
                self.original_video_height = video_stream.get('height', 0)
            else:
                self.original_video_width = 0
                self.original_video_height = 0
            self.title_entry.insert(0, os.path.splitext(os.path.basename(filepath))[0])
            self.video_duration = float(info.get('format', {}).get('duration', 0))
            if video_stream:
                self.mode_selector.set("Video+Audio")
                self.on_mode_change("Video+Audio")
                frame_path = self.ffmpeg_processor.get_frame_from_video(filepath)
                if frame_path:
                    self.load_thumbnail(frame_path, is_local=True)
                v_codec = video_stream.get('codec_name', 'N/A').upper()
                v_profile = video_stream.get('profile', 'N/A')
                v_level = video_stream.get('level')
                full_profile = f"{v_profile}@L{v_level / 10.0}" if v_level else v_profile
                v_resolution = f"{video_stream.get('width', '?')}x{video_stream.get('height', '?')}"
                v_fps = self._format_fps(video_stream.get('r_frame_rate'))
                v_bitrate = self._format_bitrate(video_stream.get('bit_rate'))
                v_pix_fmt = video_stream.get('pix_fmt', 'N/A')
                bit_depth = "10-bit" if any(x in v_pix_fmt for x in ['p10', '10le']) else "8-bit"
                color_range = video_stream.get('color_range', '').capitalize()
                v_label = f"{v_resolution} | {v_codec} ({full_profile}) @ {v_fps} fps | {v_bitrate} | {v_pix_fmt} ({bit_depth}, {color_range})"
                _, ext_with_dot = os.path.splitext(filepath)
                ext = ext_with_dot.lstrip('.')
                self.video_formats = {v_label: {
                    'format_id': 'local_video',
                    'index': video_stream.get('index', 0),
                    'width': self.original_video_width, 
                    'height': self.original_video_height, 
                    'vcodec': v_codec, 
                    'ext': ext
                }}
                self.video_quality_menu.configure(values=[v_label], state="normal")
                self.video_quality_menu.set(v_label)
                self.on_video_quality_change(v_label)
                audio_streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'audio']
                audio_labels = []
                self.audio_formats = {} 
                if not audio_streams:
                    self.audio_formats = {"-": {}}
                    self.audio_quality_menu.configure(values=["-"], state="disabled")
                else:
                    for stream in audio_streams:
                        idx = stream.get('index', '?')
                        title = stream.get('tags', {}).get('title', f"Pista de Audio {idx}")
                        is_default = stream.get('disposition', {}).get('default', 0) == 1
                        default_str = " (Default)" if is_default else ""
                        a_codec = stream.get('codec_name', 'N/A').upper()
                        a_profile = stream.get('profile', 'N/A')
                        a_channels_num = stream.get('channels', '?')
                        a_channel_layout = stream.get('channel_layout', 'N/A')
                        a_channels = f"{a_channels_num} Canales ({a_channel_layout})"
                        a_sample_rate = f"{int(stream.get('sample_rate', 0)) / 1000:.1f} kHz"
                        a_bitrate = self._format_bitrate(stream.get('bit_rate'))
                        a_label = f"{title}{default_str}: {a_codec} ({a_profile}) | {a_sample_rate} | {a_channels} | {a_bitrate}"
                        audio_labels.append(a_label)
                        self.audio_formats[a_label] = {'format_id': f'local_audio_{idx}', 'acodec': stream.get('codec_name', 'N/A')}
                    self.audio_quality_menu.configure(values=audio_labels, state="normal")
                    default_selection = next((label for label in audio_labels if "(Default)" in label), audio_labels[0])
                    self.audio_quality_menu.set(default_selection)
                    if hasattr(self, 'use_all_audio_tracks_check'):
                        if len(audio_labels) > 1:
                            self.use_all_audio_tracks_check.pack(padx=5, pady=(5,0), anchor="w")
                            self.use_all_audio_tracks_check.deselect()
                        else:
                            self.use_all_audio_tracks_check.pack_forget()
                        self.audio_quality_menu.configure(state="normal")
                self._update_warnings()
            elif audio_stream:
                self.mode_selector.set("Solo Audio")
                self.on_mode_change("Solo Audio")
                self.create_placeholder_label("🎵")
                a_codec = audio_stream.get('codec_name', 'N/A')
                a_label = f"Audio Original ({a_codec})"
                self.audio_formats = {a_label: {'format_id': 'local_audio', 'acodec': a_codec}}
                self.audio_quality_menu.configure(values=[a_label], state="normal")
                self.audio_quality_menu.set(a_label)
                self._update_warnings()
            if self.cpu_radio.cget('state') == 'normal':
                self.proc_type_var.set("CPU")
                self.update_codec_menu() 
            self.progress_label.configure(text=f"Listo para recodificar: {os.path.basename(filepath)}")
            self.progress_bar.set(1)
            self.update_download_button_state()
            self.download_button.configure(text="Iniciar Proceso", fg_color=self.PROCESS_BTN_COLOR, hover_color=self.PROCESS_BTN_HOVER)
            self.update_estimated_size()
            self._validate_recode_compatibility()
            self._on_save_in_same_folder_change()
        self.app.after(0, update_ui)

    def _format_bitrate(self, bitrate_str):
        """Convierte un bitrate en string a un formato legible (kbps o Mbps)."""
        if not bitrate_str: return "Bitrate N/A"
        try:
            bitrate = int(bitrate_str)
            if bitrate > 1_000_000:
                return f"{bitrate / 1_000_000:.2f} Mbps"
            elif bitrate > 1_000:
                return f"{bitrate / 1_000:.0f} kbps"
            return f"{bitrate} bps"
        except (ValueError, TypeError):
            return "Bitrate N/A"

    def _format_fps(self, fps_str):
        """Convierte una fracción de FPS (ej: '30000/1001') a un número decimal."""
        if not fps_str or '/' not in fps_str: return fps_str or "FPS N/A"
        try:
            num, den = map(int, fps_str.split('/'))
            if den == 0: return "FPS N/A"
            return f"{num / den:.2f}"
        except (ValueError, TypeError):
            return "FPS N/A"

    def reset_ui_for_local_file(self):
        self.title_entry.delete(0, 'end')
        self.video_formats, self.audio_formats = {}, {}
        self.video_quality_menu.configure(values=["-"], state="disabled")
        self.audio_quality_menu.configure(values=["-"], state="disabled")
        self._clear_subtitle_menus()
        self.clear_local_file_button.pack(fill="x", padx=10, pady=(0, 10))

    def reset_to_url_mode(self):
        self.keep_original_on_clip_check.configure(state="normal")
        
        self.precise_clip_check.configure(state="normal")
        self.force_full_download_check.configure(state="normal")
        
        self.local_file_path = None
        self.url_entry.configure(state="normal")
        self.analyze_button.configure(state="normal")
        self.url_entry.delete(0, 'end')
        self.title_entry.delete(0, 'end')
        self.create_placeholder_label("Miniatura")
        self.auto_save_thumbnail_check.configure(state="normal")
        self.video_formats, self.audio_formats = {}, {}
        self.video_quality_menu.configure(values=["-"], state="disabled")
        self.audio_quality_menu.configure(values=["-"], state="disabled")
        self.progress_label.configure(text="Esperando...")
        self.progress_bar.set(0)
        self._clear_subtitle_menus()
        self.save_in_same_folder_check.pack_forget()
        self.download_button.configure(text=self.original_download_text, fg_color=self.DOWNLOAD_BTN_COLOR)
        self.clear_local_file_button.pack_forget()

        self.auto_save_thumbnail_check.configure(state="normal")
        self.keep_original_checkbox.configure(state="normal")
        self.keep_original_quick_checkbox.configure(state="normal")
        # 🆕 Rehabilitar en modo extraer
        if hasattr(self, 'keep_original_extract_checkbox'):
            self.keep_original_extract_checkbox.configure(state="normal")
        self.update_download_button_state()
        self.save_in_same_folder_check.deselect()
        self._on_save_in_same_folder_change()
        self.use_all_audio_tracks_check.pack_forget()

    def _execute_local_recode(self, options):
        """
        Función que gestiona el procesamiento de archivos locales, incluyendo recorte y/o recodificación.
        
        🆕 CORREGIDO: Ahora mantiene correctamente el sufijo "_fragmento" en todos los casos.
        """
        clipped_temp_file = None
        
        try:
            source_path = self.local_file_path
            
            # 1. Determinar las intenciones del usuario
            is_fragment_mode = options.get("fragment_enabled") and (options.get("start_time") or options.get("end_time"))
            is_recode_mode = options.get("recode_video_enabled") or options.get("recode_audio_enabled")

            # --- ¡AQUÍ ESTÁ LA LÓGICA CLAVE DE LA SOLUCIÓN! ---
            if is_fragment_mode and not is_recode_mode:
                # CASO 1: El usuario SÓLO quiere cortar el archivo.
                final_clipped_path = self._execute_fragment_clipping(
                    input_filepath=source_path,
                    start_time=options.get("start_time"),
                    end_time=options.get("end_time")
                )
                self.app.after(0, self.on_process_finished, True, "Recorte completado.", final_clipped_path)
                return # Salimos de la función para evitar la recodificación.
            
            # Si llegamos aquí, significa que el usuario quiere recodificar (con o sin un recorte previo).
            input_for_recode = source_path
            
            if is_fragment_mode and is_recode_mode:
                # CASO 2: El usuario quiere CORTAR y LUEGO RECODIFICAR.
                clipped_temp_file = self._execute_fragment_clipping(
                    input_filepath=source_path,
                    start_time=options.get("start_time"),
                    end_time=options.get("end_time")
                )
                input_for_recode = clipped_temp_file

            output_dir = self.output_path_entry.get()
            if self.save_in_same_folder_check.get() == 1:
                output_dir = os.path.dirname(source_path)

            # 🆕 LÓGICA CORREGIDA DE NOMBRES
            base_filename = self.sanitize_filename(options['title'])
            
            # 🔧 PASO 1: Si se cortó, agregar "_fragmento"
            if is_fragment_mode:
                base_filename += "_fragmento"
            
            # 🔧 PASO 2: Si se recodifica, agregar "_recoded"
            # (Esto se ejecuta siempre que lleguemos aquí porque ya validamos is_recode_mode arriba)
            base_filename += "_recoded"

            selected_audio_stream_index = None
            if self.use_all_audio_tracks_check.get() == 1 and len(self.audio_formats) > 1:
                selected_audio_stream_index = "all"
            else:
                selected_audio_info = self.audio_formats.get(self.audio_quality_menu.get(), {})
                if selected_audio_info.get('format_id', '').startswith('local_audio_'):
                    selected_audio_stream_index = int(selected_audio_info['format_id'].split('_')[-1])

            selected_video_label = self.video_quality_menu.get()
            selected_video_info = self.video_formats.get(selected_video_label, {})
            selected_video_stream_index = selected_video_info.get('index')
            
            options['selected_audio_stream_index'] = selected_audio_stream_index
            options['selected_video_stream_index'] = selected_video_stream_index
            
            # 🆕 CRÍTICO: Actualizar la duración para el recorte
            if is_fragment_mode:
                start_seconds = self.time_str_to_seconds(options.get("start_time")) if options.get("start_time") else 0
                end_seconds = self.time_str_to_seconds(options.get("end_time")) if options.get("end_time") else self.video_duration
                options['duration'] = end_seconds - start_seconds
            else:
                options['duration'] = self.video_duration

            final_output_path = self._execute_recode_master(
                input_file=input_for_recode,
                output_dir=output_dir,
                base_filename=base_filename,
                recode_options=options
            )

            self.app.after(0, self.on_process_finished, True, "Proceso local completado.", final_output_path)

        except (UserCancelledError, Exception) as e:
            raise LocalRecodeFailedError(str(e))
        finally:
            if clipped_temp_file and os.path.exists(clipped_temp_file):
                try:
                    os.remove(clipped_temp_file)
                    print(f"DEBUG: Archivo de recorte temporal eliminado: {clipped_temp_file}")
                except OSError as err:
                    print(f"ADVERTENCIA: No se pudo eliminar el archivo de recorte temporal: {err}")
        
    def _on_save_in_same_folder_change(self):
        """
        Actualiza el estado de la carpeta de salida según la casilla
        'Guardar en la misma carpeta'.
        """
        if self.save_in_same_folder_check.get() == 1 and self.local_file_path:
            output_dir = os.path.dirname(self.local_file_path)
            self.output_path_entry.configure(state="normal")
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, output_dir)
            self.output_path_entry.configure(state="disabled")
            self.select_folder_button.configure(state="disabled")
        else:
            self.output_path_entry.configure(state="normal")
            self.select_folder_button.configure(state="normal")
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, self.app.default_download_path)
        self.update_download_button_state()

    def toggle_resolution_panel(self):
        if self.resolution_checkbox.get() == 1:
            self.resolution_options_frame.grid()
            
            if hasattr(self, 'original_video_width') and self.original_video_width > 0:
                if not self.width_entry.get() and not self.height_entry.get():
                    self.width_entry.delete(0, 'end')
                    self.width_entry.insert(0, str(self.original_video_width))
                    self.height_entry.delete(0, 'end')
                    self.height_entry.insert(0, str(self.original_video_height))
                    
                    if not self.aspect_ratio_lock.get():
                        self.aspect_ratio_lock.select()
                    try:
                        self.current_aspect_ratio = self.original_video_width / self.original_video_height
                    except (ValueError, ZeroDivisionError):
                        self.current_aspect_ratio = None
            
            self.on_resolution_preset_change(self.resolution_preset_menu.get())
        else:
            self.resolution_options_frame.grid_remove()

    def on_dimension_change(self, source):
        if not self.aspect_ratio_lock.get() or self.is_updating_dimension or not self.current_aspect_ratio:
            return
        try:
            self.is_updating_dimension = True
            if source == "width":
                current_width_str = self.width_entry.get()
                if current_width_str:
                    new_width = int(current_width_str)
                    new_height = int(new_width / self.current_aspect_ratio)
                    self.height_entry.delete(0, 'end')
                    self.height_entry.insert(0, str(new_height))
            elif source == "height":
                current_height_str = self.height_entry.get()
                if current_height_str:
                    new_height = int(current_height_str)
                    new_width = int(new_height * self.current_aspect_ratio)
                    self.width_entry.delete(0, 'end')
                    self.width_entry.insert(0, str(new_width))
        except (ValueError, ZeroDivisionError):
            pass
        finally:
            self.is_updating_dimension = False

    def on_aspect_lock_change(self):
        if self.aspect_ratio_lock.get():
            try:
                width_str = self.width_entry.get()
                height_str = self.height_entry.get()
                
                if width_str and height_str:
                    width = int(width_str)
                    height = int(height_str)
                    self.current_aspect_ratio = width / height
                elif hasattr(self, 'original_video_width') and self.original_video_width > 0:
                    self.current_aspect_ratio = self.original_video_width / self.original_video_height
                else:
                    self.current_aspect_ratio = None
                    
            except (ValueError, ZeroDivisionError, AttributeError):
                self.current_aspect_ratio = None
        else:
            self.current_aspect_ratio = None

    def on_resolution_preset_change(self, preset):
        # Mapa de resoluciones 16:9
        PRESET_RESOLUTIONS_16_9 = {
            "4K UHD": ("3840", "2160"),
            "2K QHD": ("2560", "1440"),
            "1080p Full HD": ("1920", "1080"),
            "720p HD": ("1280", "720"),
            "480p SD": ("854", "480")
        }

        if preset == "Personalizado":
            # Mostrar el frame manual
            self.resolution_manual_frame.grid()
            if hasattr(self, 'original_video_width') and self.original_video_width > 0:
                # Si está en blanco, rellenar con la resolución original
                if not self.width_entry.get():  
                    self.width_entry.delete(0, 'end')
                    self.width_entry.insert(0, str(self.original_video_width))
                    self.height_entry.delete(0, 'end')
                    self.height_entry.insert(0, str(self.original_video_height))
                
                # Actualizar el aspect ratio para el candado
                if self.aspect_ratio_lock.get():
                    try:
                        self.current_aspect_ratio = self.original_video_width / self.original_video_height
                    except (ValueError, ZeroDivisionError, AttributeError):
                        self.current_aspect_ratio = None
        
        elif preset in PRESET_RESOLUTIONS_16_9:
            # Si es un preset (ej. "480p SD"), ocultar el frame manual
            self.resolution_manual_frame.grid_remove()
            try:
                # Obtener las dimensiones 16:9
                width_str, height_str = PRESET_RESOLUTIONS_16_9[preset]
                width, height = int(width_str), int(height_str)

                # Rellenar las cajas de texto (aunque estén ocultas, el código de recodificación las leerá)
                self.width_entry.delete(0, 'end')
                self.width_entry.insert(0, width_str)
                self.height_entry.delete(0, 'end')
                self.height_entry.insert(0, height_str)
                
                # Actualizar el aspect ratio para el candado
                try:
                    self.current_aspect_ratio = width / height
                except ZeroDivisionError:
                    self.current_aspect_ratio = None
                    
            except Exception as e:
                print(f"Error al aplicar el preset de resolución: {e}")
        else:
            # Opción desconocida, ocultar el frame
            self.resolution_manual_frame.grid_remove()

    def toggle_audio_recode_panel(self):
        """Muestra u oculta el panel de opciones de recodificación de audio."""
        if self.recode_audio_checkbox.get() == 1:
            self.recode_audio_options_frame.pack(fill="x", padx=5, pady=5)
            self.update_audio_codec_menu()
        else:
            self.recode_audio_options_frame.pack_forget()
        self.update_recode_container_label()

    def update_audio_codec_menu(self):
        """Puebla el menú de códecs de audio, filtrando por compatibilidad con el contenedor de video."""
        target_container = self.recode_container_label.cget("text")
        compatible_codecs = self._get_compatible_audio_codecs(target_container)
        if not compatible_codecs:
            compatible_codecs = ["-"]
        self.recode_audio_codec_menu.configure(values=compatible_codecs, state="normal" if compatible_codecs[0] != "-" else "disabled")
        saved_codec = self.recode_settings.get("video_audio_codec")
        if saved_codec and saved_codec in compatible_codecs:
            self.recode_audio_codec_menu.set(saved_codec)
        else:
            if compatible_codecs:
                self.recode_audio_codec_menu.set(compatible_codecs[0])
        self.update_audio_profile_menu(self.recode_audio_codec_menu.get())

    def update_audio_profile_menu(self, selected_codec_name):
        """Puebla el menú de perfiles basado en el códec de audio seleccionado."""
        profiles = ["-"]
        if selected_codec_name != "-":
            audio_codecs = self.ffmpeg_processor.available_encoders.get("CPU", {}).get("Audio", {})
            codec_data = audio_codecs.get(selected_codec_name)
            if codec_data:
                ffmpeg_codec_name = list(filter(lambda k: k != 'container', codec_data.keys()))[0]
                profiles = list(codec_data.get(ffmpeg_codec_name, {}).keys())
        self.recode_audio_profile_menu.configure(values=profiles, state="normal" if profiles[0] != "-" else "disabled")
        saved_profile = self.recode_settings.get("video_audio_profile")
        if saved_profile and saved_profile in profiles:
            self.recode_audio_profile_menu.set(saved_profile)
        else:
            self.recode_audio_profile_menu.set(profiles[0])
        self._validate_recode_compatibility()

    def on_audio_selection_change(self, selection):
        """Se ejecuta al cambiar el códec o perfil de audio para verificar la compatibilidad."""
        self.update_audio_profile_menu(selection)
        self.update_recode_container_label()
        is_video_mode = self.mode_selector.get() == "Video+Audio"
        video_codec = self.recode_codec_menu.get()
        audio_codec = self.recode_audio_codec_menu.get()
        incompatible = False
        if is_video_mode and "ProRes" in video_codec or "DNxH" in video_codec:
            if "FLAC" in audio_codec or "Opus" in audio_codec or "Vorbis" in audio_codec:
                incompatible = True
        if incompatible:
            self.audio_compatibility_warning.grid()
        else:
            self.audio_compatibility_warning.grid_remove() 

    def update_recode_container_label(self, *args):
        """
        Determina y muestra el contenedor final, asegurando que en modo
        Video+Audio siempre se use un contenedor de video.
        """
        container = "-"
        mode = self.mode_selector.get()
        is_video_recode_on = self.recode_video_checkbox.get() == 1
        is_audio_recode_on = self.recode_audio_checkbox.get() == 1
        if mode == "Video+Audio":
            if is_video_recode_on:
                proc_type = self.proc_type_var.get()
                if proc_type:
                    codec_name = self.recode_codec_menu.get()
                    available = self.ffmpeg_processor.available_encoders.get(proc_type, {}).get("Video", {})
                    if codec_name in available:
                        container = available[codec_name].get("container", "-")
            elif is_audio_recode_on:
                container = ".mp4"
        elif mode == "Solo Audio":
            if is_audio_recode_on:
                codec_name = self.recode_audio_codec_menu.get()
                available = self.ffmpeg_processor.available_encoders.get("CPU", {}).get("Audio", {})
                if codec_name in available:
                    container = available[codec_name].get("container", "-")
        self.recode_container_label.configure(text=container)

    def manual_ffmpeg_update_check(self):
        """Inicia una comprobación manual de la actualización de FFmpeg."""
        self.update_ffmpeg_button.configure(state="disabled", text="Buscando...")
        self.ffmpeg_status_label.configure(text="FFmpeg: Verificando...")
        # Limpiar estado del otro para que no se crucen mensajes
        self.active_downloads_state["deno"] = {"text": "", "value": 0.0, "active": False}

        from src.core.setup import check_ffmpeg_status # <-- Llama a la nueva función

        def check_task():
            # Usar la nueva función de callback unificada
            status_info = check_ffmpeg_status(
                lambda text, val: self.update_setup_download_progress('ffmpeg', text, val)
            )
            # Llamar a un nuevo callback en main_window
            self.app.after(0, self.app.on_ffmpeg_check_complete, status_info)

        # Usar self.active_operation_thread para evitar conflictos
        self.active_operation_thread = threading.Thread(target=check_task, daemon=True)
        self.active_operation_thread.start()

    def manual_deno_update_check(self):
        """Inicia una comprobación manual de la actualización de Deno."""
        self.update_deno_button.configure(state="disabled", text="Buscando...")
        self.deno_status_label.configure(text="Deno: Verificando...")
        # Limpiar estado del otro para que no se crucen mensajes
        self.active_downloads_state["ffmpeg"] = {"text": "", "value": 0.0, "active": False}

        from src.core.setup import check_deno_status # <-- Llama a la nueva función

        def check_task():
            status_info = check_deno_status(
                lambda text, val: self.update_setup_download_progress('deno', text, val)
            )
            # Llamar a un nuevo callback en main_window
            self.app.after(0, self.app.on_deno_check_complete, status_info)

        self.active_operation_thread = threading.Thread(target=check_task, daemon=True)
        self.active_operation_thread.start()

    def _clear_subtitle_menus(self):
        """Restablece TODOS los controles de subtítulos a su estado inicial e inactivo."""
        self.subtitle_lang_menu.configure(state="disabled", values=["-"])
        self.subtitle_lang_menu.set("-")
        self.subtitle_type_menu.configure(state="disabled", values=["-"])
        self.subtitle_type_menu.set("-")
        self.save_subtitle_button.configure(state="disabled")
        self.auto_download_subtitle_check.configure(state="disabled")
        self.auto_download_subtitle_check.deselect()
        if hasattr(self, 'clean_subtitle_check'):
            if self.clean_subtitle_check.winfo_ismapped():
                self.clean_subtitle_check.pack_forget()
            self.clean_subtitle_check.deselect()
        self.all_subtitles = {}
        self.current_subtitle_map = {}
        self.selected_subtitle_info = None

    def on_profile_selection_change(self, profile):
        self.custom_bitrate_frame.grid_forget()
        self.custom_gif_frame.grid_remove()
        if "Bitrate Personalizado" in profile:
            self.custom_bitrate_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5)
            if not self.custom_bitrate_entry.get():
                self.custom_bitrate_entry.insert(0, "8")
        
        elif profile == "Personalizado" and self.recode_codec_menu.get() == "GIF (animado)":
            self.custom_gif_frame.grid()

        self.update_estimated_size()
        self.save_settings()
        self._validate_recode_compatibility()
        self.update_audio_codec_menu() 

    def update_download_button_state(self, *args):
        """
        Valida TODAS las condiciones necesarias y actualiza el estado del botón de descarga.
        Ahora es consciente del modo de recodificación (Rápido vs Manual).
        """
        if self.url_entry.get().strip():
            self.analyze_button.configure(state="normal")
        else:
            self.analyze_button.configure(state="disabled")

        try:
            current_recode_mode = self.recode_mode_selector.get()
            
            url_mode_ready = self.analysis_is_complete and bool(self.url_entry.get().strip())
            local_mode_ready = self.local_file_path is not None
            app_is_ready_for_action = url_mode_ready or local_mode_ready

            output_path_is_valid = bool(self.output_path_entry.get())
            if local_mode_ready and self.save_in_same_folder_check.get() == 1:
                output_path_is_valid = True

            # 🆕 VALIDACIÓN MEJORADA DE TIEMPOS
            times_are_valid = True
            self.time_warning_label.configure(text="")
            
            if self.fragment_checkbox.get() == 1 and self.video_duration > 0:
                start_str = self._get_formatted_time(self.start_h, self.start_m, self.start_s)
                end_str = self._get_formatted_time(self.end_h, self.end_m, self.end_s)
                
                # Casos válidos:
                # 1. Solo inicio (start_str existe, end_str vacío) → Desde inicio hasta el final
                # 2. Solo fin (start_str vacío, end_str existe) → Desde el principio hasta fin
                # 3. Ambos (start_str y end_str existen) → Desde inicio hasta fin
                # 4. Ninguno (ambos vacíos) → Error, no tiene sentido activar el checkbox sin tiempos
                
                if not start_str and not end_str:
                    # No hay tiempos definidos
                    times_are_valid = False
                    self.time_warning_label.configure(
                        text="⚠️ Debes especificar al menos un tiempo\n       (inicio o final)",
                        text_color="orange"
                    )
                else:
                    # Validar que los tiempos estén dentro del rango del video
                    start_seconds = self.time_str_to_seconds(start_str) if start_str else 0
                    end_seconds = self.time_str_to_seconds(end_str) if end_str else self.video_duration
                    
                    # Verificar que inicio no sea mayor que la duración
                    if start_seconds >= self.video_duration:
                        times_are_valid = False
                        self.time_warning_label.configure(
                            text=f"⚠️ El tiempo de inicio ({start_str}) supera la duración del video",
                            text_color="orange"
                        )
                    # Verificar que fin no supere la duración
                    elif end_seconds > self.video_duration:
                        times_are_valid = False
                        self.time_warning_label.configure(
                            text=f"⚠️ El tiempo final ({end_str}) supera la duración del video",
                            text_color="orange"
                        )
                    # Verificar que inicio sea menor que fin (si ambos están definidos)
                    elif start_str and end_str and start_seconds >= end_seconds:
                        times_are_valid = False
                        self.time_warning_label.configure(
                            text=f"⚠️ El tiempo de inicio debe ser menor que el final",
                            text_color="orange"
                        )

            recode_config_is_valid = True
            
            if current_recode_mode == "Modo Rápido":
                if self.apply_quick_preset_checkbox.get() == 1:
                    selected_preset = self.recode_preset_menu.get()
                    if selected_preset.startswith("- ") or not selected_preset:
                        recode_config_is_valid = False
            else:  
                if self.recode_video_checkbox.get() == 1:
                    bitrate_ok = True
                    if "Bitrate Personalizado" in self.recode_profile_menu.get():
                        try:
                            value = float(self.custom_bitrate_entry.get())
                            if not (0 < value <= 200):
                                bitrate_ok = False
                        except (ValueError, TypeError):
                            bitrate_ok = False
                    if not self.proc_type_var.get() or not bitrate_ok:
                        recode_config_is_valid = False

            action_is_selected_for_local_mode = True
            if local_mode_ready:
                if current_recode_mode == "Modo Rápido":
                    is_recode_on = self.apply_quick_preset_checkbox.get() == 1
                elif current_recode_mode == "Modo Manual":
                    is_recode_on = self.recode_video_checkbox.get() == 1 or self.recode_audio_checkbox.get() == 1
                elif current_recode_mode == "Modo Extraer":
                    # 🆕 En modo extraer, siempre hay acción seleccionada
                    is_recode_on = True
                else:
                    is_recode_on = False
                
                is_clip_on = self.fragment_checkbox.get() == 1
                
                # 🆕 Si está en Modo Extraer, no requiere otras acciones
                if current_recode_mode == "Modo Extraer":
                    action_is_selected_for_local_mode = True
                elif not is_recode_on and not is_clip_on:
                    action_is_selected_for_local_mode = False

            recode_is_compatible = self.recode_compatibility_status in ["valid", "warning"]

            if (app_is_ready_for_action and
                output_path_is_valid and
                times_are_valid and
                recode_config_is_valid and
                action_is_selected_for_local_mode and
                recode_is_compatible):
                
                button_color = self.PROCESS_BTN_COLOR if self.local_file_path else self.DOWNLOAD_BTN_COLOR
                hover_color = self.PROCESS_BTN_HOVER if self.local_file_path else self.DOWNLOAD_BTN_HOVER
                self.download_button.configure(state="normal", 
                                            fg_color=button_color, 
                                            hover_color=hover_color)
            else:
                self.download_button.configure(state="disabled", 
                                            fg_color=self.DISABLED_FG_COLOR)

        except Exception as e:
            print(f"Error inesperado al actualizar estado del botón: {e}")
            self.download_button.configure(state="disabled")

        self.update_estimated_size()

    def update_estimated_size(self):
        try:
            duration_s = float(self.video_duration)
            bitrate_mbps = float(self.custom_bitrate_entry.get())
            if duration_s > 0 and bitrate_mbps > 0:
                estimated_mb = (bitrate_mbps * duration_s) / 8
                size_str = f"~ {estimated_mb / 1024:.2f} GB" if estimated_mb >= 1024 else f"~ {estimated_mb:.1f} MB"
                self.estimated_size_label.configure(text=size_str)
            else:
                self.estimated_size_label.configure(text="N/A")
        except (ValueError, TypeError, AttributeError):
            if hasattr(self, 'estimated_size_label'):
                self.estimated_size_label.configure(text="N/A")

    def save_settings(self, event=None):
        """ 
        Actualiza la configuración de la app principal (self.app).
        La ventana principal se encargará de escribir el archivo JSON.
        """
        if not hasattr(self, 'app') or self.is_initializing: # <-- MODIFICA ESTA LÍNEA
            return
        
        if not hasattr(self, 'app'): # Prevenir error si se llama antes de tiempo
            return

        # --- Actualizar config general ---
        self.app.default_download_path = self.output_path_entry.get()
        self.app.cookies_path = self.cookie_path_entry.get()
        self.app.cookies_mode_saved = self.cookie_mode_menu.get()
        self.app.selected_browser_saved = self.browser_var.get()
        self.app.browser_profile_saved = self.browser_profile_entry.get()
        
        # --- Actualizar config de Presets ---
        self.app.custom_presets = getattr(self, 'custom_presets', [])
        
        # --- Actualizar estado de UI Modo Rápido ---
        self.app.apply_quick_preset_checkbox_state = self.apply_quick_preset_checkbox.get() == 1
        self.app.keep_original_quick_saved = self.keep_original_quick_checkbox.get() == 1
        self.app.quick_preset_saved = self.recode_preset_menu.get()

        # --- Actualizar estado de UI Modo Manual ---
        mode = self.mode_selector.get()
        codec = self.recode_codec_menu.get()
        profile = self.recode_profile_menu.get()
        proc_type = self.proc_type_var.get()
        
        if proc_type: self.app.recode_settings["proc_type"] = proc_type
        if codec != "-":
            if mode == "Video+Audio": self.app.recode_settings["video_codec"] = codec
            else: self.app.recode_settings["audio_codec"] = codec
        if profile != "-":
            if mode == "Video+Audio": self.app.recode_settings["video_profile"] = profile
            else: self.app.recode_settings["audio_profile"] = profile
            if self.recode_audio_codec_menu.get() != "-":
                self.app.recode_settings["video_audio_codec"] = self.recode_audio_codec_menu.get()
            if self.recode_audio_profile_menu.get() != "-":
                self.app.recode_settings["video_audio_profile"] = self.recode_audio_profile_menu.get()
        
        self.app.recode_settings["keep_original"] = self.keep_original_checkbox.get() == 1
        self.app.recode_settings["recode_video_enabled"] = self.recode_video_checkbox.get() == 1
        self.app.recode_settings["recode_audio_enabled"] = self.recode_audio_checkbox.get() == 1


    def _toggle_recode_panels(self):
        is_video_recode = self.recode_video_checkbox.get() == 1
        is_audio_recode = self.recode_audio_checkbox.get() == 1
        is_audio_only_mode = self.mode_selector.get() == "Solo Audio"
        if self.local_file_path:
            self.keep_original_checkbox.select()
            self.keep_original_checkbox.configure(state="disabled")
        else:
            if is_video_recode or is_audio_recode:
                self.keep_original_checkbox.configure(state="normal")
            else:
                self.keep_original_checkbox.configure(state="disabled")
        if is_video_recode and not is_audio_only_mode:
            if not self.recode_options_frame.winfo_ismapped():
                self.proc_type_var.set("")
                self.update_codec_menu()
        else:
            self.recode_options_frame.pack_forget()
        if is_audio_recode:
            if not self.recode_audio_options_frame.winfo_ismapped():
                self.update_audio_codec_menu()
        else:
            self.recode_audio_options_frame.pack_forget()
        self.recode_options_frame.pack_forget()
        self.recode_audio_options_frame.pack_forget()
        if is_video_recode and not is_audio_only_mode:
            self.recode_options_frame.pack(side="top", fill="x", padx=5, pady=5)
        if is_audio_recode:
            self.recode_audio_options_frame.pack(side="top", fill="x", padx=5, pady=5)
        self._validate_recode_compatibility()
        self._update_save_preset_visibility()
    
    def _update_save_preset_visibility(self):
        """
        Muestra/oculta el botón 'Guardar como ajuste' según si hay opciones de recodificación activas
        """
        is_video_recode = self.recode_video_checkbox.get() == 1
        is_audio_recode = self.recode_audio_checkbox.get() == 1
        mode = self.mode_selector.get()
        
        should_show = False
        
        if mode == "Video+Audio":
            should_show = is_video_recode or is_audio_recode
        elif mode == "Solo Audio":
            should_show = is_audio_recode
        
        if should_show:
            self.save_preset_frame.pack(side="bottom", fill="x", padx=0, pady=(10, 0))
        else:
            self.save_preset_frame.pack_forget()

    def _validate_recode_compatibility(self):
        """Valida la compatibilidad de las opciones de recodificación y actualiza la UI."""
        self.recode_warning_frame.pack_forget()
        
        current_recode_mode = self.recode_mode_selector.get()
        if current_recode_mode == "Modo Rápido":
            self.recode_compatibility_status = "valid"
            self.update_download_button_state()
            return
        
        mode = self.mode_selector.get()
        is_video_recode = self.recode_video_checkbox.get() == 1 and mode == "Video+Audio"
        is_audio_recode = self.recode_audio_checkbox.get() == 1
        if not is_video_recode and not is_audio_recode:
            self.recode_compatibility_status = "valid"
            self.update_download_button_state()
            return
        def get_ffmpeg_codec_name(friendly_name, proc_type, category):
            if not friendly_name or friendly_name == "-": return None
            db = self.ffmpeg_processor.available_encoders.get(proc_type, {}).get(category, {})
            codec_data = db.get(friendly_name)
            if codec_data: return next((key for key in codec_data if key != 'container'), None)
            return None
        target_container = None
        if is_video_recode:
            proc_type = self.proc_type_var.get()
            if proc_type:
                available = self.ffmpeg_processor.available_encoders.get(proc_type, {}).get("Video", {})
                target_container = available.get(self.recode_codec_menu.get(), {}).get("container")
        elif is_audio_recode:
            if mode == "Video+Audio": 
                target_container = ".mp4"  
            else: 
                available = self.ffmpeg_processor.available_encoders.get("CPU", {}).get("Audio", {})
                target_container = available.get(self.recode_audio_codec_menu.get(), {}).get("container")
        if not target_container:
            self.recode_compatibility_status = "error"
            self.update_download_button_state()
            return
        self.recode_container_label.configure(text=target_container) 
        status, message = "valid", f"✅ Combinación Válida. Contenedor final: {target_container}"
        rules = self.app.COMPATIBILITY_RULES.get(target_container, {})
        allowed_video = rules.get("video", [])
        allowed_audio = rules.get("audio", [])
        video_info = self.video_formats.get(self.video_quality_menu.get()) or {}
        original_vcodec = (video_info.get('vcodec') or 'none').split('.')[0]
        audio_info = self.audio_formats.get(self.audio_quality_menu.get()) or {}
        original_acodec = (audio_info.get('acodec') or 'none').split('.')[0]
        if mode == "Video+Audio":
            if is_video_recode:
                proc_type = self.proc_type_var.get()
                ffmpeg_vcodec = get_ffmpeg_codec_name(self.recode_codec_menu.get(), proc_type, "Video")
                if ffmpeg_vcodec and ffmpeg_vcodec not in allowed_video:
                    status, message = "error", f"❌ El códec de video ({self.recode_codec_menu.get()}) no es compatible con {target_container}."
            else:
                if not allowed_video:
                    status, message = "error", f"❌ No se puede copiar video a un contenedor de solo audio ({target_container})."
                elif original_vcodec not in allowed_video and original_vcodec != 'none':
                    status, message = "warning", f"⚠️ El video original ({original_vcodec}) no es estándar en {target_container}. Se recomienda recodificar."
        if status in ["valid", "warning"]:
            is_pro_video_format = False
            if is_video_recode:
                codec_name = self.recode_codec_menu.get()
                if "ProRes" in codec_name or "DNxH" in codec_name:
                    is_pro_video_format = True
            if is_pro_video_format and not is_audio_recode and original_acodec in ['aac', 'mp3', 'opus', 'vorbis']:
                status, message = "error", f"❌ Incompatible: No se puede copiar audio {original_acodec.upper()} a un video {codec_name}. Debes recodificar el audio a un formato sin compresión (ej: WAV)."
            else:
                if is_audio_recode:
                    ffmpeg_acodec = get_ffmpeg_codec_name(self.recode_audio_codec_menu.get(), "CPU", "Audio")
                    if ffmpeg_acodec and ffmpeg_acodec not in allowed_audio:
                        status, message = "error", f"❌ El códec de audio ({self.recode_audio_codec_menu.get()}) no es compatible con {target_container}."
                elif mode == "Video+Audio":
                    if original_acodec not in allowed_audio and original_acodec != 'none':
                        status, message = "warning", f"⚠️ El audio original ({original_acodec}) no es estándar en {target_container}. Se recomienda recodificar."
        self.recode_compatibility_status = status
        if status == "valid":
            color = "#00A400"
            self.recode_warning_label.configure(text=message, text_color=color)
        else:
            color = "#E54B4B" if status == "error" else "#E5A04B"
            self.recode_warning_label.configure(text=message, text_color=color)
        self.recode_warning_frame.pack(after=self.recode_toggle_frame, pady=5, padx=10, fill="x")
        if hasattr(self, 'use_all_audio_tracks_check') and self.use_all_audio_tracks_check.winfo_ismapped():
            is_multi_track_available = len(self.audio_formats) > 1
            if target_container in self.app.SINGLE_STREAM_AUDIO_CONTAINERS:
                self.use_all_audio_tracks_check.configure(state="disabled")
                self.use_all_audio_tracks_check.deselect()
                self.audio_quality_menu.configure(state="normal")
            elif is_multi_track_available:
                self.use_all_audio_tracks_check.configure(state="normal")
        self.update_download_button_state()

    def toggle_fps_panel(self):
        """Muestra u oculta el panel de opciones de FPS."""
        if self.fps_checkbox.get() == 1:
            self.fps_options_frame.grid()
            self.fps_mode_var.set("CFR") 
            self.toggle_fps_entry()
        else:
            self.fps_options_frame.grid_remove()

    def toggle_fps_entry_panel(self):
        if self.fps_checkbox.get() == 1:
            self.fps_value_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.fps_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        else:
            self.fps_value_label.grid_remove()
            self.fps_entry.grid_remove()

    def update_codec_menu(self, *args):
        proc_type = self.proc_type_var.get()
        mode = self.mode_selector.get()
        codecs = ["-"]
        is_recode_panel_visible = self.recode_options_frame.winfo_ismapped()
        if self.ffmpeg_processor.is_detection_complete and is_recode_panel_visible and proc_type:
            category = "Audio" if mode == "Solo Audio" else "Video"
            effective_proc = "CPU" if category == "Audio" else proc_type
            available = self.ffmpeg_processor.available_encoders.get(effective_proc, {}).get(category, {})
            if available:
                codecs = list(available.keys())
        self.recode_codec_menu.configure(values=codecs, state="normal" if codecs and codecs[0] != "-" else "disabled")
        key = "video_codec" if mode == "Video+Audio" else "audio_codec"
        saved_codec = self.recode_settings.get(key)
        if saved_codec and saved_codec in codecs:
            self.recode_codec_menu.set(saved_codec)
        else:
            self.recode_codec_menu.set(codecs[0])
        self.update_profile_menu(self.recode_codec_menu.get())
        self.update_download_button_state()
        self.save_settings()  

    def update_profile_menu(self, selected_codec_name):
        proc_type = self.proc_type_var.get()
        mode = self.mode_selector.get()
        profiles = ["-"]
        container = "-"
        if selected_codec_name != "-":
            category = "Audio" if mode == "Solo Audio" else "Video"
            effective_proc = "CPU" if category == "Audio" else proc_type
            available_codecs = self.ffmpeg_processor.available_encoders.get(effective_proc, {}).get(category, {})
            if selected_codec_name in available_codecs:
                codec_data = available_codecs[selected_codec_name]
                ffmpeg_codec_name = list(codec_data.keys())[0]
                container = codec_data.get("container", "-")
                profile_data = codec_data.get(ffmpeg_codec_name, {})
                if profile_data:
                    profiles = list(profile_data.keys())
        self.recode_profile_menu.configure(values=profiles, state="normal" if profiles and profiles[0] != "-" else "disabled", command=self.on_profile_selection_change)
        key = "video_profile" if mode == "Video+Audio" else "audio_profile"
        saved_profile = self.recode_settings.get(key)
        if saved_profile and saved_profile in profiles:
            self.recode_profile_menu.set(saved_profile)
        else:
            self.recode_profile_menu.set(profiles[0])
        self.on_profile_selection_change(self.recode_profile_menu.get())
        self.recode_container_label.configure(text=container)

        if "GIF (animado)" in selected_codec_name:
            # Si es GIF, desactiva la recodificación de audio.
            self.recode_audio_checkbox.deselect()
            self.recode_audio_checkbox.configure(state="disabled")

            # Y también desactiva las opciones generales de FPS y resolución.
            self.fps_checkbox.configure(state="disabled")
            self.fps_checkbox.deselect()
            self.resolution_checkbox.configure(state="disabled")
            self.resolution_checkbox.deselect()
            
        else:
            # Si NO es GIF, reactiva las opciones (si hay audio disponible).
            if self.has_audio_streams or self.local_file_path:
                self.recode_audio_checkbox.configure(state="normal")
            self.fps_checkbox.configure(state="normal")
            self.resolution_checkbox.configure(state="normal")

        # Estas dos llamadas son seguras y se mantienen
        self.toggle_fps_entry_panel()
        self.toggle_resolution_panel()

        self.update_download_button_state()
        self.save_settings()

    def on_mode_change(self, mode):
        print(f"DEBUG: on_mode_change llamado con mode={mode}")
        print(f"  - video_formats vacío: {not self.video_formats}")
        print(f"  - audio_formats vacío: {not self.audio_formats}")
        print(f"  - local_file_path: {self.local_file_path}")
        print(f"  - recode_main_frame empaquetado: {self.recode_main_frame.winfo_ismapped()}")
        
        # 🆕 PROTECCIÓN MEJORADA: Solo bloquear si no hay formatos Y no es modo local
        if not self.video_formats and not self.audio_formats and not self.local_file_path:
            print("DEBUG: on_mode_change llamado pero formatos no están listos aún (modo URL)")
            return
        
        print("DEBUG: ✅ CONTINUANDO con on_mode_change")
        
        self.format_warning_label.pack_forget()
        self.video_quality_label.pack_forget()
        self.video_quality_menu.pack_forget()
        if hasattr(self, 'audio_options_frame'):
            self.audio_options_frame.pack_forget()
        self.recode_video_checkbox.deselect()
        self.recode_audio_checkbox.deselect()
        self.proc_type_var.set("") 
        
        if mode == "Video+Audio":
            self.video_quality_label.pack(fill="x", padx=5, pady=(10, 0))
            self.video_quality_menu.pack(fill="x", padx=5, pady=(0, 5))
            if hasattr(self, 'audio_options_frame'):
                self.audio_options_frame.pack(fill="x")
            self.format_warning_label.pack(fill="x", padx=5, pady=(5, 5))
            self.recode_video_checkbox.grid()
            self.recode_audio_checkbox.configure(text="Recodificar Audio")
            
            # 🆕 Solo llamar a on_video_quality_change si NO es modo local
            if not self.local_file_path:
                self.on_video_quality_change(self.video_quality_menu.get())
            
        elif mode == "Solo Audio":
            # 🆕 CRÍTICO: Verificar si REALMENTE hay audio disponible
            print("DEBUG: Cambiando a modo Solo Audio")
            
            # Verificar si hay audio en ALGÚN formato
            has_any_audio = bool(self.audio_formats) or any(
                v.get('is_combined', False) for v in self.video_formats.values()
            )
            
            if not has_any_audio:
                # 🆕 No hay audio en absoluto - mostrar advertencia
                print("⚠️ ERROR: No hay audio disponible en este video")
                self.audio_quality_menu.configure(
                    state="disabled", 
                    values=["⚠️ Este video no tiene audio"]
                )
                self.audio_quality_menu.set("⚠️ Este video no tiene audio")
                self.combined_audio_map = {}
                
                # Deshabilitar el botón de descarga
                self.download_button.configure(state="disabled")
                
            elif self.audio_formats:
                # Caso 1: Hay pistas de audio separadas
                print("DEBUG: Hay pistas de audio dedicadas disponibles")
                        
            else:
                # Caso 2: Solo hay formatos combinados - extraer opciones de audio de ellos
                print("DEBUG: No hay pistas dedicadas. Extrayendo audio de formatos combinados")
                
                # Buscar todos los formatos combinados
                audio_from_combined = []
                seen_configs = set()
                
                for video_label, video_info in self.video_formats.items():
                    if video_info.get('is_combined', False):
                        acodec = video_info.get('acodec', 'unknown').split('.')[0]
                        format_id = video_info.get('format_id')
                        
                        # Crear una clave única para evitar duplicados
                        config_key = f"{acodec}_{format_id}"
                        
                        if config_key not in seen_configs:
                            seen_configs.add(config_key)
                            
                            # Extraer info de audio del formato combinado
                            label = f"Audio desde {video_label.split('(')[0].strip()} ({acodec})"
                            
                            audio_from_combined.append({
                                'label': label,
                                'format_id': format_id,
                                'acodec': acodec
                            })
                
                if audio_from_combined:
                    # Crear opciones para el menú
                    audio_options = [entry['label'] for entry in audio_from_combined]
                    
                    # Crear un mapa temporal (similar a combined_audio_map)
                    self.combined_audio_map = {
                        entry['label']: entry['format_id'] 
                        for entry in audio_from_combined
                    }
                    
                    self.audio_quality_menu.configure(state="normal", values=audio_options)
                    self.audio_quality_menu.set(audio_options[0])
                else:
                    # No hay audio disponible en absoluto
                    self.audio_quality_menu.configure(state="disabled", values=["- Sin Audio -"])
                    self.combined_audio_map = {}
            
            if hasattr(self, 'audio_options_frame'):
                self.audio_options_frame.pack(fill="x")
            self.format_warning_label.pack(fill="x", padx=5, pady=(5, 5))
            self.recode_video_checkbox.grid_remove()
            self.recode_audio_checkbox.configure(text="Activar Recodificación para Audio")
            self._update_warnings()
            
        self.recode_main_frame._parent_canvas.yview_moveto(0)
        self.recode_main_frame.pack_forget()
        self.recode_main_frame.pack(pady=(10, 0), padx=5, fill="both", expand=True)
        
        self._toggle_recode_panels()
        self.update_codec_menu()
        self.update_audio_codec_menu()
        self._populate_preset_menu()
        self._update_save_preset_visibility()

    def _on_use_all_audio_tracks_change(self):
        """Gestiona el estado del menú de audio cuando el checkbox cambia."""
        if self.use_all_audio_tracks_check.get() == 1:
            self.audio_quality_menu.configure(state="disabled")
        else:
            self.audio_quality_menu.configure(state="normal")

    def on_video_quality_change(self, selected_label):
        selected_format_info = self.video_formats.get(selected_label)
        if selected_format_info:
            is_combined = selected_format_info.get('is_combined', False)
            quality_key = selected_format_info.get('quality_key')
            
            # 🔧 MODIFICADO: Solo llenar el menú de audio si hay variantes REALES
            if is_combined and quality_key and quality_key in self.combined_variants:
                variants = self.combined_variants[quality_key]
                
                # 🆕 NUEVO: Verificar que realmente hay múltiples idiomas
                unique_languages = set()
                for variant in variants:
                    lang = variant.get('language', '')
                    if lang:
                        unique_languages.add(lang)
                
                # 🔧 CRÍTICO: Solo crear menú de idiomas si hay 2+ idiomas diferentes
                if len(unique_languages) >= 2:
                    # Crear opciones de idioma para el menú de audio
                    audio_language_options = []
                    self.combined_audio_map = {}
                    
                    for variant in variants:
                        lang_code = variant.get('language')
                        format_id = variant.get('format_id')
                        
                        if lang_code:
                            norm_code = lang_code.replace('_', '-').lower()
                            lang_name = self.app.LANG_CODE_MAP.get(
                                norm_code, 
                                self.app.LANG_CODE_MAP.get(norm_code.split('-')[0], lang_code)
                            )
                        else:
                            continue
                        
                        abr = variant.get('abr') or variant.get('tbr')
                        acodec = variant.get('acodec', 'unknown').split('.')[0]
                        
                        label = f"{lang_name} - {abr:.0f}kbps ({acodec})" if abr else f"{lang_name} ({acodec})"
                        
                        if label not in self.combined_audio_map:
                            audio_language_options.append(label)
                            self.combined_audio_map[label] = format_id
                    
                    if not audio_language_options:
                        # No hay idiomas válidos, deshabilitar el menú
                        self.audio_quality_menu.configure(state="disabled")
                        self.combined_audio_map = {}
                        print("DEBUG: No hay idiomas válidos en las variantes combinadas")
                    else:
                        # Ordenar por prioridad de idioma
                        def sort_by_lang_priority(label):
                            for variant in variants:
                                if self.combined_audio_map.get(label) == variant.get('format_id'):
                                    lang_code = variant.get('language', '')
                                    norm_code = lang_code.replace('_', '-').lower()
                                    return self.app.LANGUAGE_ORDER.get(
                                        norm_code, 
                                        self.app.LANGUAGE_ORDER.get(norm_code.split('-')[0], self.app.DEFAULT_PRIORITY)
                                    )
                            return self.app.DEFAULT_PRIORITY
                        
                        audio_language_options.sort(key=sort_by_lang_priority)
                        
                        # Actualizar el menú de audio
                        self.audio_quality_menu.configure(state="normal", values=audio_language_options)
                        self.audio_quality_menu.set(audio_language_options[0])
                        print(f"DEBUG: Menú de audio llenado con {len(audio_language_options)} idiomas")
                else:
                    # 🆕 NUEVO: Solo hay un idioma o ninguno, deshabilitar el menú
                    self.audio_quality_menu.configure(state="disabled")
                    self.combined_audio_map = {}
                    print(f"DEBUG: Combinado de un solo idioma detectado (quality_key: {quality_key})")
            else:
                # 🆕 CRÍTICO: Este else faltaba - restaurar el menú de audio normal
                print(f"DEBUG: No es combinado multiidioma, restaurando menú de audio normal")
                self.combined_audio_map = {}
                
                # Restaurar las opciones de audio originales
                a_opts = list(self.audio_formats.keys()) or ["- Sin Pistas de Audio -"]
                
                # --- INICIO DE LA MODIFICACIÓN (FIX DEL RESETEO) ---

                # 1. Obtener la selección de audio ACTUAL (la que eligió el usuario)
                current_audio_selection = self.audio_quality_menu.get()

                # 2. Buscar la mejor opción por defecto (fallback)
                default_audio_selection = a_opts[0]
                for option in a_opts:
                    if "✨" in option:
                        default_audio_selection = option
                        break
                
                # 3. Decidir qué selección usar
                selection_to_set = default_audio_selection # Usar el fallback por defecto
                if current_audio_selection in a_opts:
                    selection_to_set = current_audio_selection # ¡Ahá! Mantener la del usuario
                
                # Restaurar el menú
                self.audio_quality_menu.configure(
                    state="normal" if self.audio_formats else "disabled",
                    values=a_opts
                )
                self.audio_quality_menu.set(selection_to_set) # <-- Usar la selección decidida
                # --- FIN DE LA MODIFICACIÓN ---
            
            # Actualizar dimensiones si están disponibles
            new_width = selected_format_info.get('width')
            new_height = selected_format_info.get('height')
            if new_width and new_height and hasattr(self, 'width_entry'):
                self.width_entry.delete(0, 'end')
                self.width_entry.insert(0, str(new_width))
                self.height_entry.delete(0, 'end')
                self.height_entry.insert(0, str(new_height))
                if self.aspect_ratio_lock.get():
                    self.on_aspect_lock_change()
        
        self._update_warnings()
        self._validate_recode_compatibility()

    def _update_warnings(self):
        mode = self.mode_selector.get()
        warnings = []
        compatibility_issues = []
        unknown_issues = []
        if mode == "Video+Audio":
            video_info = self.video_formats.get(self.video_quality_menu.get())
            audio_info = self.audio_formats.get(self.audio_quality_menu.get())
            if not video_info or not audio_info: return
            virtual_format = {'vcodec': video_info.get('vcodec'), 'acodec': audio_info.get('acodec'), 'ext': video_info.get('ext')}
            compatibility_issues, unknown_issues = self._get_format_compatibility_issues(virtual_format)
            if "Lento" in self.video_quality_menu.get():
                warnings.append("• Formato de video lento para recodificar.")
        elif mode == "Solo Audio":
            audio_info = self.audio_formats.get(self.audio_quality_menu.get())
            if not audio_info: return
            virtual_format = {'acodec': audio_info.get('acodec')}
            compatibility_issues, unknown_issues = self._get_format_compatibility_issues(virtual_format)
            if audio_info.get('acodec') == 'none':
                unknown_issues.append("audio")
        if compatibility_issues:
            issues_str = ", ".join(compatibility_issues)
            warnings.append(f"• Requiere recodificación por códec de {issues_str}.")
        if unknown_issues:
            issues_str = ", ".join(unknown_issues)
            warnings.append(f"• Compatibilidad desconocida para el códec de {issues_str}.")
        if warnings:
            self.format_warning_label.configure(text="\n".join(warnings), text_color="#FFA500")
        else:
            legend_text = ("Guía de etiquetas en la lista:\n" "✨ Ideal: Formato óptimo para editar sin conversión.\n" "⚠️ Recodificar: Formato no compatible con editores.")
            self.format_warning_label.configure(text=legend_text, text_color="gray")

    def _get_format_compatibility_issues(self, format_dict):
        if not format_dict: return [], []
        compatibility_issues = []
        unknown_issues = []
        raw_vcodec = format_dict.get('vcodec')
        vcodec = raw_vcodec.split('.')[0] if raw_vcodec else 'none'
        raw_acodec = format_dict.get('acodec')
        acodec = raw_acodec.split('.')[0] if raw_acodec else 'none'
        ext = format_dict.get('ext') or 'none'
        if vcodec == 'none' and 'vcodec' in format_dict:
            unknown_issues.append("video")
        elif vcodec != 'none' and vcodec not in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_vcodecs"]:
            compatibility_issues.append(f"video ({vcodec})")
        if acodec != 'none' and acodec not in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_acodecs"]:
            compatibility_issues.append(f"audio ({acodec})")
        if vcodec != 'none' and ext not in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_exts"]:
            compatibility_issues.append(f"contenedor (.{ext})")
        return compatibility_issues, unknown_issues
    
    def _initialize_presets_file(self):
        """
        Inicializa el archivo presets.json si no existe.
        Si ya existe, lo deja como está.
        """
        if not os.path.exists(self.app.PRESETS_FILE):
            print(f"DEBUG: Archivo presets.json no encontrado. Creando con presets por defecto...")
            
            default_presets = {
                "built_in_presets": {
                    "Archivo - H.265 Normal": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "H.265 (x265)",
                        "recode_profile_name": "Calidad Media (CRF 24)",
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Buena Calidad (~192kbps)",
                        "recode_container": ".mp4"
                    },
                    "Archivo - H.265 Máxima": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "H.265 (x265)",
                        "recode_profile_name": "Calidad Alta (CRF 20)",
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Máxima Calidad (~320kbps)",
                        "recode_container": ".mp4"
                    },
                    "Web/Móvil - H.264 Liviano": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "H.264 (x264)",
                        "recode_profile_name": "Calidad Rápida (CRF 28)",
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Calidad Baja (~128kbps)",
                        "recode_container": ".mp4"
                    },
                    "Web/Móvil - H.264 Normal": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "H.264 (x264)",
                        "recode_profile_name": "Calidad Media (CRF 23)",
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Alta Calidad (~256kbps)",
                        "recode_container": ".mp4"
                    },
                    "Web/Móvil - H.264 Máxima": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "H.264 (x264)",
                        "recode_profile_name": "Alta Calidad (CRF 18)",
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Máxima Calidad (~320kbps)",
                        "recode_container": ".mp4"
                    },
                    "Edición - ProRes 422 Proxy": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "Apple ProRes (prores_aw) (Velocidad)",
                        "recode_profile_name": "422 Proxy",
                        "recode_audio_codec_name": "WAV (Sin Comprimir)",
                        "recode_audio_profile_name": "PCM 16-bit",
                        "recode_container": ".mov"
                    },
                    "Edición - ProRes 422": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "Apple ProRes (prores_ks) (Precisión)",
                        "recode_profile_name": "422 HQ",
                        "recode_audio_codec_name": "WAV (Sin Comprimir)",
                        "recode_audio_profile_name": "PCM 16-bit",
                        "recode_container": ".mov"
                    },
                    "Edición - ProRes 422 LT": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "Apple ProRes (prores_aw) (Velocidad)",
                        "recode_profile_name": "422 LT",
                        "recode_audio_codec_name": "WAV (Sin Comprimir)",
                        "recode_audio_profile_name": "PCM 16-bit",
                        "recode_container": ".mov"
                    },
                    "GIF R\u00e1pido (Baja Calidad)": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": False,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "GIF (animado)",
                        "recode_profile_name": "Baja Calidad (R\u00e1pido)",
                        "custom_bitrate_value": "8",
                        "custom_gif_fps": "",
                        "custom_gif_width": "",
                        "recode_container": ".gif",
                        "recode_audio_codec_name": "-",
                        "recode_audio_profile_name": "-",
                        "fps_force_enabled": False,
                        "fps_value": "",
                        "resolution_change_enabled": False,
                        "res_width": "",
                        "res_height": "",
                        "no_upscaling_enabled": False
                    },
                    "GIF (Media Calidad)": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": False,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "GIF (animado)",
                        "recode_profile_name": "Calidad Media (540p, 24fps)",
                        "custom_bitrate_value": "8",
                        "custom_gif_fps": "",
                        "custom_gif_width": "",
                        "recode_container": ".gif",
                        "recode_audio_codec_name": "-",
                        "recode_audio_profile_name": "-",
                        "fps_force_enabled": False,
                        "fps_value": "",
                        "resolution_change_enabled": False,
                        "res_width": "",
                        "res_height": "",
                        "no_upscaling_enabled": False
                    },
                    "GIF (Alta Calidad)": {
                        "mode_compatibility": "Video+Audio",
                        "recode_video_enabled": True,
                        "recode_audio_enabled": False,
                        "keep_original_file": True,
                        "recode_proc": "CPU",
                        "recode_codec_name": "GIF (animado)",
                        "recode_profile_name": "Calidad Alta (720p, 30fps)",
                        "custom_bitrate_value": "8",
                        "custom_gif_fps": "",
                        "custom_gif_width": "",
                        "recode_container": ".gif",
                        "recode_audio_codec_name": "-",
                        "recode_audio_profile_name": "-",
                        "fps_force_enabled": False,
                        "fps_value": "",
                        "resolution_change_enabled": False,
                        "res_width": "",
                        "res_height": "",
                        "no_upscaling_enabled": False
                    },
                    "Audio - MP3 128kbps": {
                        "mode_compatibility": "Solo Audio",
                        "recode_video_enabled": False,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_audio_codec_name": "MP3 (libmp3lame)",
                        "recode_audio_profile_name": "128kbps (CBR)",
                        "recode_container": ".mp3"
                    },
                    "Audio - MP3 192kbps": {
                        "mode_compatibility": "Solo Audio",
                        "recode_video_enabled": False,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_audio_codec_name": "MP3 (libmp3lame)",
                        "recode_audio_profile_name": "192kbps (CBR)",
                        "recode_container": ".mp3"
                    },
                    "Audio - MP3 320kbps": {
                        "mode_compatibility": "Solo Audio",
                        "recode_video_enabled": False,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_audio_codec_name": "MP3 (libmp3lame)",
                        "recode_audio_profile_name": "320kbps (CBR)",
                        "recode_container": ".mp3"
                    },
                    "Audio - AAC 192kbps": {
                        "mode_compatibility": "Solo Audio",
                        "recode_video_enabled": False,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_audio_codec_name": "AAC",
                        "recode_audio_profile_name": "Buena Calidad (~192kbps)",
                        "recode_container": ".m4a"
                    },
                    "Audio - WAV 16-bit (Sin pérdida)": {
                        "mode_compatibility": "Solo Audio",
                        "recode_video_enabled": False,
                        "recode_audio_enabled": True,
                        "keep_original_file": True,
                        "recode_audio_codec_name": "WAV (Sin Comprimir)",
                        "recode_audio_profile_name": "PCM 16-bit",
                        "recode_container": ".wav"
                    }
                },
                "custom_presets": []
            }
        
            try:
                with open(self.app.PRESETS_FILE, 'w') as f:
                    json.dump(default_presets, f, indent=4)
                print(f"DEBUG: presets.json creado exitosamente en {self.app.PRESETS_FILE}")
            except IOError as e:
                print(f"ERROR: No se pudo crear presets.json: {e}")
        else:
            print(f"DEBUG: presets.json ya existe. Cargando...")

    def _load_presets(self):
        """
        Carga los presets desde presets.json.
        Retorna un diccionario con built_in_presets y custom_presets.
        """
        try:
            if os.path.exists(self.app.PRESETS_FILE):
                with open(self.app.PRESETS_FILE, 'r') as f:
                    presets_data = json.load(f)
                    return presets_data
            else:
                print("ERROR: presets.json no encontrado")
                return {"built_in_presets": {}, "custom_presets": []}
        except (json.JSONDecodeError, IOError) as e:
            print(f"ERROR: No se pudo cargar presets.json: {e}")
            return {"built_in_presets": {}, "custom_presets": []}
        
    def open_save_preset_dialog(self):
        """Abre el diálogo para guardar un preset personalizado."""
        dialog = SavePresetDialog(self.app)
        self.app.wait_window(dialog)
            
        if dialog.result:
            self._save_custom_preset(dialog.result)

    def export_preset_file(self):
        """
        Exporta el preset seleccionado como archivo .dowp_preset
        """
        selected_preset_name = self.recode_preset_menu.get()
        
        if selected_preset_name.startswith("- ") or not selected_preset_name:
            messagebox.showwarning("Selecciona un preset", "Por favor, selecciona un preset para exportar.")
            return
        
        preset_data = None
        for custom_preset in self.custom_presets:
            if custom_preset["name"] == selected_preset_name:
                preset_data = custom_preset["data"]
                break
        
        if preset_data is None:
            messagebox.showwarning(
                "No se puede exportar",
                "Solo puedes exportar presets personalizados.\nLos presets integrados no se pueden exportar."
            )
            return
        
        preset_content = self._create_preset_file_content(preset_data, selected_preset_name)
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".dowp_preset",
            filetypes=[("DowP Preset", "*.dowp_preset"), ("JSON", "*.json"), ("All Files", "*.*")],
            initialfile=f"{selected_preset_name}.dowp_preset"
        )
        
        self.app.lift()
        self.app.focus_force()
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(preset_content, f, indent=4)
                
                messagebox.showinfo(
                    "Exportado",
                    f"El preset '{selected_preset_name}' ha sido exportado exitosamente.\n\nUbicación: {file_path}"
                )
                print(f"DEBUG: Preset exportado: {file_path}")
            except Exception as e:
                messagebox.showerror("Error al exportar", f"No se pudo exportar el preset:\n{e}")
                print(f"ERROR al exportar preset: {e}")

    def import_preset_file(self):
        """
        Importa un archivo .dowp_preset y lo agrega a presets personalizados
        """
        file_path = filedialog.askopenfilename(
            filetypes=[("DowP Preset", "*.dowp_preset"), ("JSON", "*.json"), ("All Files", "*.*")],
            title="Selecciona un archivo .dowp_preset para importar"
        )
        
        self.app.lift()
        self.app.focus_force()
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r') as f:
                preset_content = json.load(f)
            
            if not self._validate_preset_file(preset_content):
                messagebox.showerror(
                    "Archivo inválido",
                    "El archivo no es un preset válido o está corrupto."
                )
                return
            
            preset_name = preset_content.get("preset_name", "Sin nombre")
            preset_data = preset_content.get("data")
            
            existing_preset = next((p for p in self.custom_presets if p["name"] == preset_name), None)
            if existing_preset:
                result = messagebox.askyesno(
                    "Preset duplicado",
                    f"El preset '{preset_name}' ya existe.\n¿Deseas sobrescribirlo?"
                )
                if not result:
                    return
                
                self.custom_presets = [p for p in self.custom_presets if p["name"] != preset_name]
            
            self.custom_presets.append({
                "name": preset_name,
                "data": preset_data
            })
            
            presets_data = self._load_presets()
            presets_data["custom_presets"] = self.custom_presets
            
            with open(self.app.PRESETS_FILE, 'w') as f:
                json.dump(presets_data, f, indent=4)
            
            self._populate_preset_menu()
            self.app.batch_tab._populate_batch_preset_menu()
            self.app.batch_tab._populate_global_preset_menu()
            
            messagebox.showinfo(
                "Importado",
                f"El preset '{preset_name}' ha sido importado exitosamente.\nAhora está disponible en Modo Rápido."
            )
            print(f"DEBUG: Preset importado: {preset_name}")
            
        except json.JSONDecodeError:
            messagebox.showerror(
                "Error",
                "El archivo no es un JSON válido."
            )
        except Exception as e:
            messagebox.showerror(
                "Error al importar",
                f"No se pudo importar el preset:\n{e}"
            )
            print(f"ERROR al importar preset: {e}")

    def delete_preset_file(self):
        """
        Elimina el preset personalizado seleccionado
        """
        selected_preset_name = self.recode_preset_menu.get()
        
        if selected_preset_name.startswith("- ") or not selected_preset_name:
            messagebox.showwarning("Selecciona un preset", "Por favor, selecciona un preset para eliminar.")
            return
        
        is_custom = any(p["name"] == selected_preset_name for p in self.custom_presets)
        if not is_custom:
            messagebox.showwarning(
                "No se puede eliminar",
                "Solo puedes eliminar presets personalizados.\nLos presets integrados no se pueden eliminar."
            )
            return
        
        result = messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Estás seguro de que deseas eliminar el preset '{selected_preset_name}'?\n\nEsta acción no se puede deshacer."
        )
        
        if not result:
            return
        
        try:
            self.custom_presets = [p for p in self.custom_presets if p["name"] != selected_preset_name]
            
            presets_data = self._load_presets()
            presets_data["custom_presets"] = self.custom_presets
            
            with open(self.app.PRESETS_FILE, 'w') as f:
                json.dump(presets_data, f, indent=4)
            
            self._populate_preset_menu()
            self.app.batch_tab._populate_batch_preset_menu()
            self.app.batch_tab._populate_global_preset_menu()
            
            messagebox.showinfo(
                "Eliminado",
                f"El preset '{selected_preset_name}' ha sido eliminado exitosamente."
            )
            print(f"DEBUG: Preset eliminado: {selected_preset_name}")
            
        except Exception as e:
            messagebox.showerror(
                "Error al eliminar",
                f"No se pudo eliminar el preset:\n{e}"
            )
            print(f"ERROR al eliminar preset: {e}")
    
    def _save_custom_preset(self, preset_name):
        """
        Guarda la configuración actual como un preset personalizado en presets.json
        """
        try:
            current_preset_data = {
                "mode_compatibility": self.mode_selector.get(),
                "recode_video_enabled": self.recode_video_checkbox.get() == 1,
                "recode_audio_enabled": self.recode_audio_checkbox.get() == 1,
                "keep_original_file": self.keep_original_checkbox.get() == 1,
                "recode_proc": self.proc_type_var.get(),
                "recode_codec_name": self.recode_codec_menu.get(),
                "recode_profile_name": self.recode_profile_menu.get(),
                "custom_bitrate_value": self.custom_bitrate_entry.get(),
                "custom_gif_fps": self.custom_gif_fps_entry.get(),
                "custom_gif_width": self.custom_gif_width_entry.get(),
                "recode_container": self.recode_container_label.cget("text"),
                "recode_audio_codec_name": self.recode_audio_codec_menu.get(),
                "recode_audio_profile_name": self.recode_audio_profile_menu.get(),
                "fps_force_enabled": self.fps_checkbox.get() == 1,
                "fps_value": self.fps_entry.get(),
                "resolution_change_enabled": self.resolution_checkbox.get() == 1,
                "res_width": self.width_entry.get(),
                "res_height": self.height_entry.get(),
                "no_upscaling_enabled": self.no_upscaling_checkbox.get() == 1,
            }
            
            presets_data = self._load_presets()
            
            if preset_name in presets_data["built_in_presets"]:
                messagebox.showerror(
                    "Nombre duplicado",
                    f"El nombre '{preset_name}' ya existe en los presets integrados.\nPor favor, usa otro nombre."
                )
                return
            
            existing_preset = next((p for p in presets_data["custom_presets"] if p["name"] == preset_name), None)
            if existing_preset:
                result = messagebox.askyesno(
                    "Preset ya existe",
                    f"El preset '{preset_name}' ya existe.\n¿Deseas sobrescribirlo?"
                )
                if result:
                    presets_data["custom_presets"] = [p for p in presets_data["custom_presets"] if p["name"] != preset_name]
                else:
                    return
            
            presets_data["custom_presets"].append({
                "name": preset_name,
                "data": current_preset_data
            })
            
            with open(self.app.PRESETS_FILE, 'w') as f:
                json.dump(presets_data, f, indent=4)
            
            print(f"DEBUG: Preset personalizado '{preset_name}' guardado exitosamente.")
            
            self.built_in_presets = presets_data.get("built_in_presets", {})
            self.custom_presets = presets_data.get("custom_presets", [])
            
            self._populate_preset_menu()
            self.app.batch_tab._populate_batch_preset_menu()
            self.app.batch_tab._populate_global_preset_menu()
            
            messagebox.showinfo(
                "Éxito",
                f"El ajuste '{preset_name}' ha sido guardado.\nAhora está disponible en Modo Rápido."
            )
            
        except Exception as e:
            print(f"ERROR al guardar preset: {e}")
            messagebox.showerror(
                "Error al guardar",
                f"No se pudo guardar el ajuste:\n{e}"
            )

    def _create_preset_file_content(self, preset_data, preset_name):
        """
        Crea el contenido de un archivo .dowp_preset con validación.
        Retorna un diccionario que será guardado como JSON.
        """
        import hashlib
        
        preset_content = {
            "preset_name": preset_name,
            "preset_version": "1.0",
            "data": preset_data
        }
        
        content_string = json.dumps(preset_data, sort_keys=True)
        checksum = hashlib.sha256(content_string.encode()).hexdigest()
        preset_content["checksum"] = checksum
        
        return preset_content
    
    def _validate_preset_file(self, preset_content):
        """
        Valida la integridad de un archivo .dowp_preset.
        Retorna True si es válido, False si no.
        """
        import hashlib
        
        if not isinstance(preset_content, dict):
            print("ERROR: El archivo no es un preset válido (no es diccionario)")
            return False
        
        if "checksum" not in preset_content or "data" not in preset_content:
            print("ERROR: El preset no tiene estructura válida")
            return False
        
        stored_checksum = preset_content.get("checksum")
        preset_data = preset_content.get("data")
        
        content_string = json.dumps(preset_data, sort_keys=True)
        calculated_checksum = hashlib.sha256(content_string.encode()).hexdigest()
        
        if stored_checksum != calculated_checksum:
            print("ERROR: El checksum no coincide (archivo corrupto o modificado)")
            return False
        
        return True

    def sanitize_filename(self, filename):
        """
        Sanitización completa con doble límite (caracteres + bytes).
        
        Límites:
        - 150 caracteres (límite visual/UX)
        - 220 bytes UTF-8 (límite técnico filesystem)
        
        Compatible con todos los idiomas y sistemas modernos.
        """
        import unicodedata
        
        original_filename = filename
        
        # 1. Normalizar Unicode (NFC)
        filename = unicodedata.normalize('NFC', filename)
        
        # 2. Eliminar caracteres de control
        filename = ''.join(
            char for char in filename 
            if unicodedata.category(char)[0] != 'C'
        )
        
        # 3. Eliminar caracteres prohibidos por filesystems
        forbidden_chars = r'[\\/:\*\?"<>|]'
        filename = re.sub(forbidden_chars, '', filename)
        
        # 4. Normalizar espacios múltiples
        filename = re.sub(r'\s+', ' ', filename).strip()
        
        # 5. Eliminar puntos y espacios al final (Windows)
        filename = filename.rstrip('. ')
        
        # 6. 🆕 LÍMITE VISUAL: 150 caracteres
        max_chars = 150
        if len(filename) > max_chars:
            filename = filename[:max_chars]
            filename = filename.rstrip('. ')
            print(f"ℹ️ Título truncado de {len(original_filename)} a {max_chars} caracteres")
        
        # 7. LÍMITE TÉCNICO: 220 bytes UTF-8
        max_bytes = 220
        if len(filename.encode('utf-8')) > max_bytes:
            filename_bytes = filename.encode('utf-8')[:max_bytes]
            filename = filename_bytes.decode('utf-8', errors='ignore')
            filename = filename.rstrip('. ')
            print(f"ℹ️ Título truncado de {len(filename.encode('utf-8'))} a {max_bytes} bytes")
        
        # 8. Fallback de seguridad
        if not filename or filename.strip() == '':
            filename = "video_descargado"
            print(f"⚠️ Título vacío después de sanitización. Usando fallback.")
        
        # 9. Log si hubo cambios (útil para debugging)
        if filename != original_filename:
            print(f"📝 Nombre ajustado:")
            print(f"   Original: {original_filename[:100]}{'...' if len(original_filename) > 100 else ''}")
            print(f"   Final: {filename}")
        
        return filename

    def create_placeholder_label(self, text="Miniatura", font_size=14):
        """Crea el placeholder de miniatura"""
        if self.thumbnail_label: 
            self.thumbnail_label.destroy()
        
        # ✅ Limpiar variables de hover (pero NO eliminar el atributo)
        if hasattr(self, '_original_image_backup'):
            self._original_image_backup = None  # Mantener como None, no del
        
        if hasattr(self, '_hover_text_label') and self._hover_text_label is not None:
            try:
                if self._hover_text_label.winfo_exists():
                    self._hover_text_label.destroy()
            except:
                pass
            self._hover_text_label = None
        
        font = ctk.CTkFont(size=font_size)
        
        self.thumbnail_label = ctk.CTkLabel(self.dnd_overlay, text=text, font=font)
        self.thumbnail_label.pack(expand=True, fill="both")
        
        self.pil_image = None
        
        if hasattr(self, 'save_thumbnail_button'): 
            self.save_thumbnail_button.configure(state="disabled")
        if hasattr(self, 'send_thumbnail_to_imagetools_button'):
            self.send_thumbnail_to_imagetools_button.configure(state="disabled")
        if hasattr(self, 'auto_save_thumbnail_check'):
            self.auto_save_thumbnail_check.deselect()
            self.auto_save_thumbnail_check.configure(state="normal")
        
        self.dnd_overlay.lift()

    def _on_cookie_detail_change(self, event=None):
        """Callback for when specific cookie details (path, browser, profile) change."""
        print("DEBUG: Cookie details changed. Clearing analysis cache.")
        self.analysis_cache.clear()
        self.save_settings()

    def on_cookie_mode_change(self, mode):
        """Muestra u oculta las opciones de cookies según el modo seleccionado."""
        
        # 🆕 NUEVO: Manejar la opción de ayuda
        if mode == "¿Cómo obtener cookies?":
            self._open_cookie_extension_link()
            # Restaurar al modo anterior (o "No usar" si no había)
            previous_mode = getattr(self, '_previous_cookie_mode', "No usar")
            self.cookie_mode_menu.set(previous_mode)
            return
        
        # Guardar el modo actual para poder volver después
        self._previous_cookie_mode = mode
        
        print("DEBUG: Cookie mode changed. Clearing analysis cache.")
        self.analysis_cache.clear()
        
        if mode == "Archivo Manual...":
            self.manual_cookie_frame.pack(fill="x", padx=10, pady=(0, 10))
            self.browser_options_frame.pack_forget()
        elif mode == "Desde Navegador":
            self.manual_cookie_frame.pack_forget()
            self.browser_options_frame.pack(fill="x", padx=10, pady=(0, 10))
        else:  # "No usar"
            self.manual_cookie_frame.pack_forget()
            self.browser_options_frame.pack_forget()
        
        self.save_settings()

    def _open_cookie_extension_link(self):
        """Abre la página de GitHub de la extensión Get cookies.txt LOCALLY"""
        import webbrowser
        webbrowser.open_new_tab("https://github.com/kairi003/Get-cookies.txt-LOCALLY")
        print("DEBUG: Abriendo enlace de extensión de cookies en el navegador")

    def toggle_manual_thumbnail_button(self):
        is_checked = self.auto_save_thumbnail_check.get() == 1
        has_image = self.pil_image is not None
        
        # Ambos botones se habilitan/deshabilitan juntos
        if is_checked or not has_image:
            self.save_thumbnail_button.configure(state="disabled")
            if hasattr(self, 'send_thumbnail_to_imagetools_button'):
                self.send_thumbnail_to_imagetools_button.configure(state="disabled")
        else:
            self.save_thumbnail_button.configure(state="normal")
            if hasattr(self, 'send_thumbnail_to_imagetools_button'):
                self.send_thumbnail_to_imagetools_button.configure(state="normal")

    def toggle_manual_subtitle_button(self):
        """Activa/desactiva el botón 'Descargar Subtítulos'."""
        is_auto_download = self.auto_download_subtitle_check.get() == 1
        has_valid_subtitle_selected = hasattr(self, 'selected_subtitle_info') and self.selected_subtitle_info is not None
        if is_auto_download or not has_valid_subtitle_selected:
            self.save_subtitle_button.configure(state="disabled")
        else:
            self.save_subtitle_button.configure(state="normal")

    def on_language_change(self, selected_language_name):
        """Se ejecuta cuando el usuario selecciona un idioma. Pobla el segundo menú."""
        possible_codes = [code for code, name in self.app.LANG_CODE_MAP.items() if name == selected_language_name]
        actual_lang_code = None
        for code in possible_codes:
            primary_part = code.split('-')[0].lower()
            if primary_part in self.all_subtitles:
                actual_lang_code = primary_part
                break
        if not actual_lang_code:
            actual_lang_code = possible_codes[0].split('-')[0].lower() if possible_codes else selected_language_name
        sub_list = self.all_subtitles.get(actual_lang_code, [])
        filtered_subs = []
        added_types = set()
        for sub_info in sub_list:
            ext = sub_info.get('ext')
            is_auto = sub_info.get('automatic', False)
            sub_type_key = (is_auto, ext)
            if sub_type_key in added_types:
                continue
            filtered_subs.append(sub_info)
            added_types.add(sub_type_key)

        def custom_type_sort_key(sub_info):
            is_auto = 1 if sub_info.get('automatic', False) else 0
            is_srt = 0 if sub_info.get('ext') == 'srt' else 1
            return (is_auto, is_srt)
        sorted_subs = sorted(filtered_subs, key=custom_type_sort_key)
        type_display_names = []
        self.current_subtitle_map = {}
        for sub_info in sorted_subs:
            origin = "Automático" if sub_info.get('automatic') else "Manual"
            ext = sub_info.get('ext', 'N/A')
            full_lang_code = sub_info.get('lang', '')
            display_name = self._get_subtitle_display_name(full_lang_code)
            label = f"{origin} (.{ext}) - {display_name}"
            type_display_names.append(label)
            self.current_subtitle_map[label] = sub_info 
        if type_display_names:
            self.subtitle_type_menu.configure(state="normal", values=type_display_names)
            self.subtitle_type_menu.set(type_display_names[0])
            self.on_subtitle_selection_change(type_display_names[0]) 
        else:
            self.subtitle_type_menu.configure(state="disabled", values=["-"])
            self.subtitle_type_menu.set("-")
        self.toggle_manual_subtitle_button()

    def _get_subtitle_display_name(self, lang_code):
        """Obtiene un nombre legible para un código de idioma de subtítulo, simple o compuesto."""
        parts = lang_code.split('-')
        if len(parts) == 1:
            return self.app.LANG_CODE_MAP.get(lang_code, lang_code)
        elif self.app.LANG_CODE_MAP.get(lang_code):
            return self.app.LANG_CODE_MAP.get(lang_code)
        else:
            original_lang = self.app.LANG_CODE_MAP.get(parts[0], parts[0])
            translated_part = '-'.join(parts[1:])
            translated_lang = self.app.LANG_CODE_MAP.get(translated_part, translated_part)
            return f"{original_lang} (Trad. a {translated_lang})"

    def on_subtitle_selection_change(self, selected_type):
        """
        Se ejecuta cuando el usuario selecciona un tipo/formato de subtítulo.
        CORREGIDO: Ahora muestra la opción de conversión para CUALQUIER formato que no sea SRT.
        """
        self.selected_subtitle_info = self.current_subtitle_map.get(selected_type)
        should_show_option = False
        if self.selected_subtitle_info:
            subtitle_ext = self.selected_subtitle_info.get('ext')
            if subtitle_ext != 'srt':
                should_show_option = True
        is_visible = self.clean_subtitle_check.winfo_ismapped()
        if should_show_option:
            if not is_visible:
                self.clean_subtitle_check.pack(padx=10, pady=(0, 5), anchor="w")
        else:
            if is_visible:
                self.clean_subtitle_check.pack_forget()
            self.clean_subtitle_check.deselect()
        print(f"Subtítulo seleccionado final: {self.selected_subtitle_info}")
        self.toggle_manual_subtitle_button()
        self.save_settings()

    def select_output_folder(self):
        folder_path = filedialog.askdirectory()
        self.app.lift()
        self.app.focus_force()
        if folder_path:
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, folder_path)
            self.app.default_download_path = folder_path
            self.save_settings()
            self.update_download_button_state()

    def open_last_download_folder(self):
        """Abre la carpeta contenedora del último resultado (archivo o carpeta)."""
        if not self.last_download_path or not os.path.exists(self.last_download_path):
            print("ERROR: No hay una ruta válida para mostrar.")
            return
        
        path = os.path.normpath(self.last_download_path)
        
        # ✅ Si es una carpeta (extracción), abrir la carpeta CONTENEDORA
        if os.path.isdir(path):
            folder_to_open = os.path.dirname(path)
            print(f"DEBUG: Abriendo carpeta contenedora de: {path}")
        # ✅ Si es un archivo, abrir la carpeta contenedora y seleccionar el archivo
        else:
            folder_to_open = path
            print(f"DEBUG: Abriendo carpeta y seleccionando archivo: {path}")
        
        try:
            system = platform.system()
            if system == "Windows":
                if os.path.isdir(path):
                    # Abrir carpeta contenedora sin seleccionar nada
                    subprocess.Popen(['explorer', folder_to_open])
                else:
                    # Abrir y seleccionar archivo
                    subprocess.Popen(['explorer', '/select,', path])
            elif system == "Darwin":
                if os.path.isdir(path):
                    subprocess.Popen(['open', folder_to_open])
                else:
                    subprocess.Popen(['open', '-R', path])
            else:
                # Linux siempre abre la carpeta contenedora
                subprocess.Popen(['xdg-open', folder_to_open if os.path.isdir(path) else os.path.dirname(path)])
        except Exception as e:
            print(f"Error al abrir carpeta: {e}")

    def select_cookie_file(self):
        filepath = filedialog.askopenfilename(title="Selecciona tu archivo cookies.txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if filepath:
            self.cookie_path_entry.delete(0, 'end')
            self.cookie_path_entry.insert(0, filepath)
            self.app.cookies_path = filepath
            self.save_settings()

    def save_thumbnail(self):
        if not self.pil_image: return
        clean_title = self.sanitize_filename(self.title_entry.get() or "miniatura")
        initial_dir = self.output_path_entry.get()
        if not os.path.isdir(initial_dir):
            initial_dir = self.default_download_path or str(Path.home() / "Downloads")
        save_path = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=f"{clean_title}.jpg",
            defaultextension=".jpg", 
            filetypes=[("JPEG Image", "*.jpg"), ("PNG Image", "*.png")]
        )
        if save_path:
            try:
                if save_path.lower().endswith((".jpg", ".jpeg")): self.pil_image.convert("RGB").save(save_path, quality=95)
                else: self.pil_image.save(save_path)
                self.on_process_finished(True, f"Miniatura guardada en {os.path.basename(save_path)}", save_path)
            except Exception as e: self.on_process_finished(False, f"Error al guardar miniatura: {e}", None)

    def _execute_subtitle_download_subprocess(self, url, subtitle_info, save_path):
        try:
            output_dir = os.path.dirname(save_path)
            files_before = set(os.listdir(output_dir))
            lang_code = subtitle_info['lang']
            
            # Usar el template por defecto de yt-dlp
            output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
            
            command = [
                'yt-dlp', '--no-warnings', '--write-sub',
                '--sub-langs', lang_code,
                '--skip-download', '--no-playlist',
                '-o', output_template 
            ]
            
            # Verificar si se debe convertir a SRT
            should_convert_to_srt = self.clean_subtitle_check.winfo_ismapped() and self.clean_subtitle_check.get() == 1
            
            if should_convert_to_srt:
                command.extend(['--sub-format', 'best/vtt/best'])
                command.extend(['--convert-subs', 'srt'])
            else:
                command.extend(['--sub-format', subtitle_info['ext']])
                
            if subtitle_info.get('automatic', False):
                command.append('--write-auto-sub')
                
            cookie_mode = self.cookie_mode_menu.get()
            if cookie_mode == "Archivo Manual..." and self.cookie_path_entry.get():
                command.extend(['--cookies', self.cookie_path_entry.get()])
            elif cookie_mode != "No usar":
                browser_arg = self.browser_var.get()
                profile = self.browser_profile_entry.get()
                if profile: 
                    browser_arg += f":{profile}"
                command.extend(['--cookies-from-browser', browser_arg])
                
            command.extend(['--ffmpeg-location', self.ffmpeg_processor.ffmpeg_path])    
            command.append(url)
            
            self.app.after(0, self.update_progress, 0, "Iniciando proceso de yt-dlp...")
            print(f"\n\nDEBUG: Comando final enviado a yt-dlp:\n{' '.join(command)}\n\n")
            
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8', 
                errors='ignore', 
                creationflags=creationflags
            )
            
            stdout_lines = []
            stderr_lines = []
            
            def read_stream(stream, lines_buffer):
                for line in iter(stream.readline, ''):
                    lines_buffer.append(line.strip())
                    
            stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines))
            stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines))
            stdout_thread.start()
            stderr_thread.start()
            stdout_thread.join()
            stderr_thread.join()
            process.wait()
            
            print("--- [yt-dlp finished] ---\n")
            
            if process.returncode != 0:
                full_error_output = "\n".join(stdout_lines) + "\n" + "\n".join(stderr_lines)
                raise Exception(f"El proceso de yt-dlp falló:\n{full_error_output}")
                
            files_after = set(os.listdir(output_dir))
            new_files = files_after - files_before
            
            if not new_files:
                raise FileNotFoundError("yt-dlp terminó, pero no se detectó ningún archivo de subtítulo nuevo.")
            
            # Filtrar solo archivos de subtítulos
            subtitle_extensions = {'.vtt', '.srt', '.ass', '.ssa'}
            new_subtitle_files = [f for f in new_files if os.path.splitext(f)[1].lower() in subtitle_extensions]
            
            if not new_subtitle_files:
                raise FileNotFoundError(f"yt-dlp descargó archivos, pero ninguno es un subtítulo. Archivos nuevos: {new_files}")
            
            new_filename = new_subtitle_files[0]
            downloaded_subtitle_path = os.path.join(output_dir, new_filename)
            
            print(f"DEBUG: Subtítulo descargado: {downloaded_subtitle_path}")
            
            # 🔧 OPCIÓN 1: Mantener el código de idioma en el nombre
            # Extraer el nombre base del archivo descargado (sin el código de idioma)
            downloaded_name = os.path.basename(downloaded_subtitle_path)
            downloaded_ext = os.path.splitext(downloaded_name)[1]
            
            # Construir el nuevo nombre: usar el nombre elegido por el usuario + código de idioma + extensión
            user_chosen_name = os.path.splitext(os.path.basename(save_path))[0]
            final_filename = f"{user_chosen_name}.{lang_code}{downloaded_ext}"
            final_output_path = os.path.join(output_dir, final_filename)
            
            # Renombrar
            if downloaded_subtitle_path != final_output_path:
                if os.path.exists(final_output_path):
                    os.remove(final_output_path)
                os.rename(downloaded_subtitle_path, final_output_path)
                print(f"DEBUG: Subtítulo renombrado a: {final_output_path}")
            
            # 🔧 CORREGIDO: Limpiar/convertir SIEMPRE que sea .srt (ya sea que venga así o fue convertido)
            if final_output_path.lower().endswith('.srt'):
                self.app.after(0, self.update_progress, 90, "Limpiando y estandarizando formato SRT...")
                final_output_path = clean_and_convert_vtt_to_srt(final_output_path)
                print(f"DEBUG: Subtítulo limpiado: {final_output_path}")
            
            self.app.after(0, self.on_process_finished, True, 
                        f"Subtítulo guardado en {os.path.basename(final_output_path)}", 
                        final_output_path)
                        
        except Exception as e:
            self.app.after(0, self.on_process_finished, False, 
                        f"Error al descargar subtítulo: {e}", None)

    def save_subtitle(self):
        """
        Guarda el subtítulo seleccionado invocando a yt-dlp en un subproceso.
        """
        subtitle_info = self.selected_subtitle_info
        if not subtitle_info:
            self.update_progress(0, "Error: No hay subtítulo seleccionado.")
            return
        subtitle_ext = subtitle_info.get('ext', 'txt')
        clean_title = self.sanitize_filename(self.title_entry.get() or "subtitle")
        initial_filename = f"{clean_title}.{subtitle_ext}"
        save_path = filedialog.asksaveasfilename(
            defaultextension=f".{subtitle_ext}",
            filetypes=[(f"{subtitle_ext.upper()} Subtitle", f"*.{subtitle_ext}"), ("All files", "*.*")],
            initialfile=initial_filename
        )
        if save_path:
            video_url = self.url_entry.get()
            self.download_button.configure(state="disabled")
            self.analyze_button.configure(state="disabled")
            threading.Thread(
                target=self._execute_subtitle_download_subprocess, 
                args=(video_url, subtitle_info, save_path), 
                daemon=True
            ).start()

    def cancel_operation(self):
        """
        Maneja la cancelación de cualquier operación activa.
        Mata procesos huérfanos de FFmpeg para liberar a yt-dlp inmediatamente.
        """
        print("DEBUG: Botón de Cancelar presionado.")
        self.cancellation_event.set()
        
        # 1. Cancelar el procesador interno (si se está usando recodificación local)
        self.ffmpeg_processor.cancel_current_process()
        
        # 2. FUERZA BRUTA: Matar ffmpeg.exe para liberar a yt-dlp
        # yt-dlp lanza ffmpeg como subproceso interno sin darnos el PID.
        # Si no matamos ffmpeg, yt-dlp espera hasta que termine la descarga para cancelar.
        if os.name == 'nt':
            try:
                print("DEBUG: Intentando matar procesos FFmpeg externos (yt-dlp)...")
                subprocess.run(
                    ['taskkill', '/F', '/IM', 'ffmpeg.exe', '/T'], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 # CREATE_NO_WINDOW
                )
            except Exception as e:
                print(f"ADVERTENCIA: No se pudieron matar procesos FFmpeg externos: {e}")

        # 3. Cancelar subprocesos propios (si tenemos el PID guardado)
        if self.active_subprocess_pid:
            print(f"DEBUG: Intentando terminar el árbol de procesos para el PID: {self.active_subprocess_pid}")
            try:
                subprocess.run(
                    ['taskkill', '/PID', str(self.active_subprocess_pid), '/T', '/F'],
                    check=True,
                    capture_output=True, 
                    text=True,
                    creationflags=0x08000000 # CREATE_NO_WINDOW
                )
                print(f"DEBUG: Proceso {self.active_subprocess_pid} terminado.")
                time.sleep(1.0)
                gc.collect()
            except Exception as e:
                print(f"ADVERTENCIA: Falló taskkill por PID: {e}")
            
            self.active_subprocess_pid = None

    def start_download_thread(self):
        url = self.url_entry.get()
        output_path = self.output_path_entry.get()
        has_input = url or self.local_file_path
        has_output = output_path
        
        if not has_input or not has_output:
            error_msg = "Error: Falta la carpeta de salida."
            if not has_input:
                error_msg = "Error: No se ha proporcionado una URL ni se ha importado un archivo."
            self.progress_label.configure(text=error_msg)
            return
        
        # 🆕 VALIDACIÓN: Verificar que hay audio si está en modo Solo Audio
        if self.mode_selector.get() == "Solo Audio":
            audio_label = self.audio_quality_menu.get()
            if "no tiene audio" in audio_label.lower() or audio_label == "-":
                self.progress_label.configure(text="Error: Este video no tiene audio disponible.")
                return
        # --- Preparación de UI (Ahora esconde AMBOS botones de resultado) ---
        self.download_button.configure(text="Cancelar", fg_color=self.CANCEL_BTN_COLOR, hover_color=self.CANCEL_BTN_HOVER, command=self.cancel_operation)
        self.analyze_button.configure(state="disabled") 
        self.save_subtitle_button.configure(state="disabled")
        self.open_folder_button.configure(state="disabled")
        self.send_to_imagetools_button.pack_forget() # <-- ESCONDER EL NUEVO BOTÓN
        
        self.cancellation_event.clear()
        self.progress_bar.set(0)
        self.update_progress(0, "Preparando proceso...")
        
        # --- Recolección de Opciones Base (Comunes) ---
        options = {
            "url": url, "output_path": output_path,
            "title": self.title_entry.get() or "video_descargado",
            "mode": self.mode_selector.get(),
            "video_format_label": self.video_quality_menu.get(),
            "audio_format_label": self.audio_quality_menu.get(),
            "recode_video_enabled": self.recode_video_checkbox.get() == 1,
            "recode_audio_enabled": self.recode_audio_checkbox.get() == 1,
            "keep_original_file": self.keep_original_checkbox.get() == 1,
            "recode_proc": self.proc_type_var.get(),
            "recode_codec_name": self.recode_codec_menu.get(),
            "recode_profile_name": self.recode_profile_menu.get(),
            "custom_bitrate_value": self.custom_bitrate_entry.get(),
            "custom_gif_fps": self.custom_gif_fps_entry.get() or "15",
            "custom_gif_width": self.custom_gif_width_entry.get() or "480",
            "recode_container": self.recode_container_label.cget("text"),
            "recode_audio_enabled": self.recode_audio_checkbox.get() == 1,
            "recode_audio_codec_name": self.recode_audio_codec_menu.get(),
            "recode_audio_profile_name": self.recode_audio_profile_menu.get(),
            "speed_limit": self.speed_limit_entry.get(),
            "cookie_mode": self.cookie_mode_menu.get(),
            "cookie_path": self.cookie_path_entry.get(),
            "selected_browser": self.browser_var.get(),
            "browser_profile": self.browser_profile_entry.get(),
            "download_subtitles": self.auto_download_subtitle_check.get() == 1,
            "selected_subtitle_info": self.selected_subtitle_info,
            "fps_force_enabled": self.fps_checkbox.get() == 1,
            "fps_value": self.fps_entry.get(),
            "resolution_change_enabled": self.resolution_checkbox.get() == 1,
            "res_width": self.width_entry.get(),
            "res_height": self.height_entry.get(),
            "no_upscaling_enabled": self.no_upscaling_checkbox.get() == 1,
            "resolution_preset": self.resolution_preset_menu.get(),
            "original_width": self.original_video_width,
            "original_height": self.original_video_height,
            "fragment_enabled": self.fragment_checkbox.get() == 1,
            "start_time": self._get_formatted_time(self.start_h, self.start_m, self.start_s),
            "end_time": self._get_formatted_time(self.end_h, self.end_m, self.end_s),
            "precise_clip_enabled": self.precise_clip_check.get() == 1,
            "force_full_download": self.force_full_download_check.get() == 1, # <-- NUEVO
            "keep_original_on_clip": self.keep_original_on_clip_check.get() == 1 
        }

        # --- EL NUEVO "ROUTER" LÓGICO ---
        recode_mode = self.recode_mode_selector.get()

        if recode_mode == "Modo Rápido" or recode_mode == "Modo Manual":
            
            # --- Lógica de Recodificación (tu código existente) ---
            print("DEBUG: Iniciando Hilo de Recodificación/Descarga.")
            
            # Recolectar opciones de recodificación
            if recode_mode == "Modo Rápido":
                if self.apply_quick_preset_checkbox.get() == 1:
                    selected_preset_name = self.recode_preset_menu.get()
                    preset_params = self._find_preset_params(selected_preset_name)
                    options.update(preset_params)
                options["keep_original_file"] = self.keep_original_quick_checkbox.get() == 1
                
                # Llamar al hilo de trabajo
                self.active_operation_thread = threading.Thread(target=self._execute_download_and_recode, args=(options,), daemon=True)
                self.active_operation_thread.start()

            elif recode_mode == "Modo Manual":
                manual_options = {
                    "recode_video_enabled": self.recode_video_checkbox.get() == 1,
                    "recode_audio_enabled": self.recode_audio_checkbox.get() == 1,
                    "keep_original_file": self.keep_original_checkbox.get() == 1,
                    "recode_proc": self.proc_type_var.get(),
                    "recode_codec_name": self.recode_codec_menu.get(),
                    "recode_profile_name": self.recode_profile_menu.get(),
                    "custom_bitrate_value": self.custom_bitrate_entry.get(),
                    "custom_gif_fps": self.custom_gif_fps_entry.get() or "15",
                    "custom_gif_width": self.custom_gif_width_entry.get() or "480",
                    "recode_container": self.recode_container_label.cget("text"),
                    "recode_audio_codec_name": self.recode_audio_codec_menu.get(),
                    "recode_audio_profile_name": self.recode_audio_profile_menu.get(),
                    "fps_force_enabled": self.fps_checkbox.get() == 1,
                    "fps_value": self.fps_entry.get(),
                    "resolution_change_enabled": self.resolution_checkbox.get() == 1,
                    "res_width": self.width_entry.get(),
                    "res_height": self.height_entry.get(),
                    "no_upscaling_enabled": self.no_upscaling_checkbox.get() == 1,
                    "resolution_preset": self.resolution_preset_menu.get(),
                    "original_width": self.original_video_width,
                    "original_height": self.original_video_height,
                }
                options.update(manual_options)
                
                # Llamar al hilo de trabajo
                self.active_operation_thread = threading.Thread(target=self._execute_download_and_recode, args=(options,), daemon=True)
                self.active_operation_thread.start()

            elif recode_mode == "Modo Extraer":
                # --- NUEVA Lógica de Extracción ---
                print("DEBUG: Iniciando Hilo de Extracción.")
                
                # Recolectar opciones de EXTRACCIÓN
                extract_options = {
                    "extract_type": self.extract_type_menu.get(),
                    "extract_format": "jpg" if self.extract_format_menu.get() == "JPG (tamaño reducido)" else "png",
                    "extract_jpg_quality": self.extract_jpg_quality_entry.get() or "2",
                    "extract_fps": self.extract_fps_entry.get() or None
                }
                options.update(extract_options)
                
                # Llamar al Hilo de trabajo NUEVO
                self.active_operation_thread = threading.Thread(target=self._execute_extraction_thread, args=(options,), daemon=True)
                self.active_operation_thread.start()

        elif recode_mode == "Modo Extraer":
            
            # --- NUEVA Lógica de Extracción ---
            print("DEBUG: Iniciando Hilo de Extracción.")
            
            # 1. Recolectar opciones de EXTRACCIÓN
            extract_options = {
                "extract_type": self.extract_type_menu.get(),
                "extract_format": "jpg" if self.extract_format_menu.get() == "JPG (tamaño reducido)" else "png",
                "extract_jpg_quality": self.extract_jpg_quality_entry.get() or "2",
                "extract_fps": self.extract_fps_entry.get() or None
            }
            options.update(extract_options) # Añadirlas a las opciones base
            
            # 2. Llamar al Hilo de trabajo NUEVO
            self.active_operation_thread = threading.Thread(target=self._execute_extraction_thread, args=(options,), daemon=True)
            self.active_operation_thread.start()

    def _execute_download_and_recode(self, options):
        process_successful = False
        downloaded_filepath = None
        recode_phase_started = False
        keep_file_on_cancel = None
        final_recoded_path = None
        cleanup_required = True
        user_facing_title = "" 
        backup_file_path = None
        audio_extraction_fallback = False
        temp_video_for_extraction = None
        conflict_resolved = False
        
        if self.local_file_path:
            try:
                self._execute_local_recode(options)
            except (LocalRecodeFailedError, UserCancelledError) as e:
                if isinstance(e, LocalRecodeFailedError) and e.temp_filepath and os.path.exists(e.temp_filepath):
                    try:
                        os.remove(e.temp_filepath)
                        print(f"DEBUG: Archivo temporal de recodificación eliminado: {e.temp_filepath}")
                    except OSError as a:
                        print(f"ERROR: No se pudo eliminar el archivo temporal '{e.temp_filepath}': {a}")
                self.app.after(0, self.on_process_finished, False, str(e), None)
            finally:
                self.active_operation_thread = None
            return
            
        try:
            if options["mode"] == "Solo Audio":
                # Verificar si realmente hay audio dedicado o solo combinados
                audio_info = self.audio_formats.get(options["audio_format_label"], {})
                if not audio_info.get('format_id'):
                    audio_extraction_fallback = True
                    print("DEBUG: No hay pistas de audio dedicadas o formato_id inválido. Se activó el fallback de extracción desde el video.")
                    best_video_label = next(iter(self.video_formats))
                    options["video_format_label"] = best_video_label
                
            final_output_path_str = options["output_path"]
            user_facing_title = self.sanitize_filename(options['title'])
            base_filename = user_facing_title  
            title_to_check = user_facing_title
            output_path = Path(final_output_path_str)
            conflicting_file = None
            video_format_info = self.video_formats.get(options["video_format_label"], {})
            audio_format_info = self.audio_formats.get(options["audio_format_label"], {})
            mode = options["mode"]
            expected_ext = self._predict_final_extension(video_format_info, audio_format_info, mode)
            final_filename_to_check = f"{user_facing_title}{expected_ext}"
            full_path_to_check = Path(output_path) / final_filename_to_check

            final_filename_to_check = f"{user_facing_title}{expected_ext}"
            full_path_to_check = os.path.join(final_output_path_str, final_filename_to_check)
            
            # --- REFACTORIZADO ---
            # La lógica de conflicto ahora está en una sola función.
            # Esta llamada pausará el hilo si es necesario.
            final_download_path, backup_file_path = self._resolve_output_path(full_path_to_check)
            conflict_resolved = True
            
            # Actualiza el 'user_facing_title' por si se renombró el archivo.
            # (El '.stem' de Pathlib obtiene el nombre sin extensión)
            user_facing_title = Path(final_download_path).stem
            base_filename = user_facing_title
            # --- FIN REFACTORIZADO ---
            
            downloaded_filepath, temp_video_for_extraction = self._perform_download(
                options, 
                user_facing_title,  # <- Pasa el título ya resuelto
                audio_extraction_fallback
            )
                        
            filepath_to_process = self._handle_optional_clipping(downloaded_filepath, options)
                                          
            if self.cancellation_event.is_set():
                raise UserCancelledError("Proceso cancelado por el usuario.")

            self._save_thumbnail_if_enabled(filepath_to_process)
            
            if options.get("download_subtitles"):
                subtitle_info = options.get("selected_subtitle_info")
                if subtitle_info:
                    try:
                        output_dir = os.path.dirname(downloaded_filepath)
                        base_name = os.path.splitext(os.path.basename(downloaded_filepath))[0]
                        lang_code = subtitle_info['lang']
                        
                        # 🔧 Buscar el archivo de subtítulo descargado
                        import glob
                        
                        # Posibles patrones de nombre
                        possible_patterns = [
                            os.path.join(output_dir, f"{base_name}.{lang_code}.srt"),
                            os.path.join(output_dir, f"{base_name}.{lang_code}.vtt"),
                            os.path.join(output_dir, f"{base_name}.srt"),
                            os.path.join(output_dir, f"{base_name}.vtt"),
                        ]
                        
                        found_subtitle_path = None
                        for pattern in possible_patterns:
                            if os.path.exists(pattern):
                                found_subtitle_path = pattern
                                print(f"DEBUG: Encontrado subtítulo: {found_subtitle_path}")
                                break
                        
                        # Si no se encuentra con patrones específicos, buscar con glob
                        if not found_subtitle_path:
                            search_pattern = os.path.join(output_dir, f"{base_name}.{lang_code}.*")
                            matches = glob.glob(search_pattern)
                            subtitle_matches = [m for m in matches if m.lower().endswith(('.srt', '.vtt', '.ass', '.ssa'))]
                            if subtitle_matches:
                                found_subtitle_path = subtitle_matches[0]
                                print(f"DEBUG: Encontrado subtítulo con glob: {found_subtitle_path}")
                        
                        if found_subtitle_path:
                            # 🔧 NUEVO: Convertir a SRT si está marcada la opción Y el archivo no es SRT
                            should_convert = self.clean_subtitle_check.winfo_ismapped() and self.clean_subtitle_check.get() == 1
                            
                            if should_convert and not found_subtitle_path.lower().endswith('.srt'):
                                self.app.after(0, self.update_progress, 98, "Convirtiendo subtítulo a SRT...")
                                print(f"DEBUG: Convirtiendo {found_subtitle_path} a SRT")
                                
                                # Convertir VTT a SRT manualmente si es necesario
                                srt_path = os.path.splitext(found_subtitle_path)[0] + '.srt'
                                
                                # Usar la función de limpieza que también convierte
                                converted_path = clean_and_convert_vtt_to_srt(found_subtitle_path)
                                found_subtitle_path = converted_path
                                print(f"DEBUG: Subtítulo convertido a: {found_subtitle_path}")
                            
                            # Limpiar/estandarizar si es SRT (siempre, sin importar si fue convertido o ya era SRT)
                            if found_subtitle_path.lower().endswith('.srt'):
                                self.app.after(0, self.update_progress, 99, "Estandarizando formato SRT...")
                                print(f"DEBUG: Limpiando subtítulo SRT: {found_subtitle_path}")
                                found_subtitle_path = clean_and_convert_vtt_to_srt(found_subtitle_path)
                                print(f"DEBUG: Subtítulo limpiado: {found_subtitle_path}")
                        else:
                            print(f"ADVERTENCIA: No se encontró el archivo de subtítulo para '{base_name}' con idioma '{lang_code}'")
                            
                    except Exception as sub_e:
                        print(f"ADVERTENCIA: Falló el procesamiento automático del subtítulo: {sub_e}")

            if audio_extraction_fallback:
                self.app.after(0, self.update_progress, 95, "Extrayendo pista de audio...")
                audio_ext = audio_format_info.get('ext', 'm4a')
                final_audio_path = os.path.join(final_output_path_str, f"{user_facing_title}.{audio_ext}")
                # Aquí 'filepath_to_process' debe ser usado para la extracción
                filepath_to_process = self.ffmpeg_processor.extract_audio(
                    input_file=temp_video_for_extraction,
                    output_file=final_audio_path,
                    duration=self.video_duration,
                    progress_callback=self.update_progress,
                    cancellation_event=self.cancellation_event
                )
                try:
                    os.remove(temp_video_for_extraction)
                    print(f"DEBUG: Video temporal '{temp_video_for_extraction}' eliminado.")
                    temp_video_for_extraction = None 
                except OSError as e:
                    print(f"ADVERTENCIA: No se pudo eliminar el video temporal: {e}")

            if options.get("recode_video_enabled") or options.get("recode_audio_enabled"):
                recode_phase_started = True
                
                recode_base_filename = user_facing_title + "_recoded"
                
                final_recoded_path = self._execute_recode_master(
                    input_file=filepath_to_process, # <--- CORRECCIÓN 1: Usar el archivo correcto para recodificar
                    output_dir=final_output_path_str,
                    base_filename=recode_base_filename,
                    recode_options=options
                )
                
                if not options.get("keep_original_file", False):
                    # Si no queremos conservar el "original", eliminamos el archivo que se usó para la recodificación.
                    if os.path.exists(filepath_to_process):
                        os.remove(filepath_to_process) # <--- CORRECCIÓN 2: Eliminar el archivo correcto
                
                self.app.after(0, self.on_process_finished, True, "Recodificación completada", final_recoded_path)
                process_successful = True
            else: 
                # Si no hay recodificación, el archivo final es el que se procesó (que podría ser el fragmento).
                self.app.after(0, self.on_process_finished, True, "Descarga completada", filepath_to_process) # <--- CORRECCIÓN 3: Reportar el archivo correcto
                process_successful = True

        except UserCancelledError as e:
            if not conflict_resolved:
                cleanup_required = False
         
            error_message = str(e)

            if downloaded_filepath is None and not recode_phase_started:
                cleanup_required = False

            should_ask_to_keep_file = recode_phase_started and not options.get("keep_original_file", False) and not self.app.is_shutting_down
            if should_ask_to_keep_file:
                self.app.ui_request_data = {
                    "type": "ask_yes_no", "title": "Fallo en la Recodificación",
                    "message": "La descarga del archivo original se completó, pero la recodificación fue cancelada.\n\n¿Deseas conservar el archivo original descargado?"
                }
                self.app.ui_response_event.clear()
                self.app.ui_request_event.set()
                self.app.ui_response_event.wait()
                
                if self.app.ui_response_data.get("result", False):
                    keep_file_on_cancel = downloaded_filepath
                    self.app.after(0, lambda: self.on_process_finished(False, "Recodificación cancelada. Archivo original conservado.", keep_file_on_cancel, False))

                else:
                    self.app.after(0, lambda: self.on_process_finished(False, error_message, downloaded_filepath, False))

            else:
                self.app.after(0, lambda: self.on_process_finished(False, error_message, downloaded_filepath, False))

        except PlaylistDownloadError as e:
            print(f"DEBUG: Se capturó un error específico de Playlist: {e}")
            
            # Comprobar si el flag de análisis está activo
            if self.analysis_was_playlist:
                print("DEBUG: El análisis original fue de una playlist. Mostrando diálogo.")
                
                # 1. Pedir a la UI que muestre el diálogo
                self.app.ui_request_data = {
                    "type": "ask_playlist_error",
                    "filename": options["url"] # Mostrar la URL original
                }
                self.app.ui_response_event.clear()
                self.app.ui_request_event.set()
                
                # 2. Esperar la respuesta del usuario
                self.app.ui_response_event.wait()
                user_choice = self.app.ui_response_data.get("result", "cancel")
                
                if user_choice == "send_to_batch":
                    # 3. Lógica para enviar a Lotes
                    # Usamos 'after' para asegurarnos de que se ejecute en el hilo de la UI
                    self.app.after(0, self._send_url_to_batch, options["url"])
                    error_message = "Elemento enviado a la pestaña de Lotes."
                    self.app.after(0, lambda: self.on_process_finished(False, error_message, None, False))
                
                else: # "cancel"
                    # 4. Cancelar normal
                    error_message = "Descarga de colección cancelada por el usuario."
                    self.app.after(0, lambda: self.on_process_finished(False, error_message, None, False))
            
            else:
                # 5. Si no era una playlist (error inesperado), mostrar el error genérico
                print("DEBUG: Error tipo Playlist, pero el análisis no fue de playlist. Mostrando error normal.")
                cleaned_message = self._clean_ansi_codes(str(e))
                self.app.after(0, lambda: self.on_process_finished(False, cleaned_message, downloaded_filepath, True))

        except Exception as e:
            cleaned_message = self._clean_ansi_codes(str(e))
            self.app.after(0, lambda: self.on_process_finished(False, cleaned_message, downloaded_filepath, True))

            should_ask_user = recode_phase_started and not options.get("keep_original_file", False) and not self.app.is_shutting_down
            if should_ask_user:
                self.app.ui_request_data = {
                    "type": "ask_yes_no", "title": "Fallo en la Recodificación",
                    "message": "La descarga del archivo original se completó, pero la recodificación falló.\n\n¿Deseas conservar el archivo original descargado?"
                }
                self.app.ui_response_event.clear()
                self.app.ui_request_event.set()
                self.app.ui_response_event.wait()
                if self.app.ui_response_data.get("result", False):
                    keep_file_on_cancel = downloaded_filepath
        finally:
            self._perform_cleanup(
                process_successful, 
                recode_phase_started, 
                final_recoded_path, 
                temp_video_for_extraction, 
                backup_file_path, 
                cleanup_required, 
                user_facing_title, 
                options,  
                keep_file_on_cancel, 
                downloaded_filepath
            )

    def _execute_recode_master(self, input_file, output_dir, base_filename, recode_options):
        """
        Función maestra y unificada que maneja toda la lógica de recodificación.
        Es llamada tanto por el modo URL como por el modo Local.
        """
        final_recoded_path = None
        backup_file_path = None
        
        try:
            self.app.after(0, self.update_progress, 0, "Preparando recodificación...")
            final_container = recode_options["recode_container"]
            if not recode_options['recode_video_enabled'] and not recode_options['recode_audio_enabled']:
                _, original_extension = os.path.splitext(input_file)
                final_container = original_extension

            final_filename_with_ext = f"{base_filename}{final_container}"
            desired_recoded_path = os.path.join(output_dir, final_filename_with_ext)
            
            # Resolver conflictos de archivo
            final_recoded_path, backup_file_path = self._resolve_output_path(desired_recoded_path)

            temp_output_path = final_recoded_path + ".temp"

            final_ffmpeg_params = []
            pre_params = []

            # --- INICIO DE CORRECCIÓN (Muxer vs Contenedor) ---
            container_ext = recode_options['recode_container']
            
            # Buscar un muxer específico en el mapa (ej: .m4a -> mp4)
            # Usamos self.app.FORMAT_MUXER_MAP
            muxer_name = self.app.FORMAT_MUXER_MAP.get(container_ext, container_ext.lstrip('.'))
            
            final_ffmpeg_params.extend(['-f', muxer_name])
            print(f"DEBUG: [Muxer] Contenedor: {container_ext}, Muxer: {muxer_name}")
            # --- FIN DE CORRECCIÓN ---

            if recode_options.get("fragment_enabled"):
                if recode_options.get("start_time"): 
                    pre_params.extend(['-ss', recode_options.get("start_time")])
                if recode_options.get("end_time"): 
                    pre_params.extend(['-to', recode_options.get("end_time")])

            # ====== PROCESAMIENTO DE VIDEO ======
            if recode_options['mode'] != "Solo Audio":
                if recode_options["recode_video_enabled"]:
                    final_ffmpeg_params.extend(["-metadata:s:v:0", "rotate=0"])
                    proc = recode_options["recode_proc"]
                    codec_db = self.ffmpeg_processor.available_encoders[proc]["Video"]
                    codec_data = codec_db.get(recode_options["recode_codec_name"])
                    ffmpeg_codec_name = next((k for k in codec_data if k != 'container'), None)
                    profile_params_list = codec_data[ffmpeg_codec_name].get(recode_options["recode_profile_name"])

                    if profile_params_list == "CUSTOM_GIF":
                        try:
                            fps = int(recode_options["custom_gif_fps"])
                            width = int(recode_options["custom_gif_width"])
                            filter_string = f"[0:v] fps={fps},scale={width}:-1,split [a][b];[a] palettegen [p];[b][p] paletteuse"
                            final_ffmpeg_params.extend(['-filter_complex', filter_string])
                        except (ValueError, TypeError):
                            raise Exception("Valores de FPS/Ancho para GIF no son válidos.")

                    elif isinstance(profile_params_list, str) and "CUSTOM_BITRATE" in profile_params_list:
                        bitrate_mbps = float(recode_options["custom_bitrate_value"])
                        bitrate_k = int(bitrate_mbps * 1000)
                        if "nvenc" in ffmpeg_codec_name:
                            # CORREGIDO: Añadido pix_fmt para evitar error con archivos 4:2:2
                            params_str = f"-c:v {ffmpeg_codec_name} -preset p5 -rc vbr -b:v {bitrate_k}k -maxrate {bitrate_k}k -pix_fmt yuv420p"
                        else:
                            params_str = f"-c:v {ffmpeg_codec_name} -b:v {bitrate_k}k -maxrate {bitrate_k}k -bufsize {bitrate_k*2}k -pix_fmt yuv420p"
                        final_ffmpeg_params.extend(params_str.split())
                    else: 
                        final_ffmpeg_params.extend(profile_params_list)

                    # Filtros de video (FPS y resolución)
                    video_filters = []
                    if recode_options.get("fps_force_enabled") and recode_options.get("fps_value"):
                        video_filters.append(f'fps={recode_options["fps_value"]}')
                    
                    if recode_options.get("resolution_change_enabled"):
                        preset = recode_options.get("resolution_preset")
                        target_w, target_h = 0, 0

                        PRESET_RESOLUTIONS_16_9 = {
                            "4K UHD": (3840, 2160),
                            "2K QHD": (2560, 1440),
                            "1080p Full HD": (1920, 1080),
                            "720p HD": (1280, 720),
                            "480p SD": (854, 480)
                        }

                        try:
                            if preset == "Personalizado":
                                target_w = int(recode_options["res_width"])
                                target_h = int(recode_options["res_height"])
                            elif preset in PRESET_RESOLUTIONS_16_9:
                                w_16_9, h_16_9 = PRESET_RESOLUTIONS_16_9[preset]
                                
                                original_width = recode_options.get("original_width", 0)
                                original_height = recode_options.get("original_height", 0)
                                
                                if original_width > 0 and original_height > 0 and original_width < original_height:
                                    target_w, target_h = h_16_9, w_16_9
                                else:
                                    target_w, target_h = w_16_9, h_16_9

                            if target_w > 0 and target_h > 0:
                                if recode_options.get("no_upscaling_enabled"):
                                    original_width = recode_options.get("original_width", 0)
                                    original_height = recode_options.get("original_height", 0)
                                    
                                    if original_width > 0 and target_w > original_width:
                                        target_w = original_width
                                    if original_height > 0 and target_h > original_height:
                                        target_h = original_height
                                
                                video_filters.append(f'scale={target_w}:{target_h}')

                        except (ValueError, TypeError) as e:
                            print(f"ERROR: No se pudieron parsear los valores de resolución. {e}")
                            pass

                    if video_filters and "filter_complex" not in final_ffmpeg_params:
                        final_ffmpeg_params.extend(['-vf', ",".join(video_filters)])
                else:
                    final_ffmpeg_params.extend(["-c:v", "copy"])

            # ====== PROCESAMIENTO DE AUDIO (CORREGIDO) ======
            is_gif_format = "GIF" in recode_options.get("recode_codec_name", "")

            if not is_gif_format:
                is_pro_video_format = False
                if recode_options["recode_video_enabled"]:
                    if any(x in recode_options["recode_codec_name"] for x in ["ProRes", "DNxH"]):
                        is_pro_video_format = True
                
                if is_pro_video_format:
                    # Formatos ProRes/DNxHD requieren audio sin comprimir
                    final_ffmpeg_params.extend(["-c:a", "pcm_s16le"])
                elif recode_options["recode_audio_enabled"]:
                    # Recodificación de audio activada
                    audio_codec_db = self.ffmpeg_processor.available_encoders["CPU"]["Audio"]
                    audio_codec_data = audio_codec_db.get(recode_options["recode_audio_codec_name"])
                    ffmpeg_audio_codec = next((k for k in audio_codec_data if k != 'container'), None)
                    audio_profile_params = audio_codec_data[ffmpeg_audio_codec].get(recode_options["recode_audio_profile_name"])
                    if audio_profile_params:
                        final_ffmpeg_params.extend(audio_profile_params)
                else:
                    # Copiar audio sin recodificar
                    final_ffmpeg_params.extend(["-c:a", "copy"])

            # ====== CONSTRUCCIÓN DE OPCIONES PARA FFmpegProcessor ======
            command_options = {
                "input_file": input_file, 
                "output_file": temp_output_path,
                "duration": recode_options.get('duration', 0), 
                "ffmpeg_params": final_ffmpeg_params,
                "pre_params": pre_params, 
                "mode": recode_options.get('mode'),
                "selected_video_stream_index": None if "-filter_complex" in final_ffmpeg_params else recode_options.get('selected_video_stream_index'),
                "selected_audio_stream_index": None if is_gif_format else recode_options.get('selected_audio_stream_index')
            }

            # Ejecutar recodificación
            self.ffmpeg_processor.execute_recode(
                command_options, 
                self.update_progress, 
                self.cancellation_event
            )

            # Renombrar archivo temporal al nombre final
            if os.path.exists(temp_output_path):
                os.rename(temp_output_path, final_recoded_path)
            
            # Eliminar backup si existía
            if backup_file_path and os.path.exists(backup_file_path):
                os.remove(backup_file_path)
            
            return final_recoded_path
            
        except Exception as e:
            # Limpieza en caso de error
            if os.path.exists(temp_output_path):
                try: 
                    os.remove(temp_output_path)
                except OSError: 
                    pass
            
            if backup_file_path and os.path.exists(backup_file_path):
                try: 
                    os.rename(backup_file_path, final_recoded_path)
                except OSError: 
                    pass
            
            raise e

    def _perform_download(self, options, user_facing_title, audio_extraction_fallback):
        downloaded_filepath = None
        temp_video_for_extraction = None
        self.app.after(0, self.update_progress, 0, "Iniciando descarga...")
        
        video_format_info = self.video_formats.get(options["video_format_label"], {})
        audio_format_info = self.audio_formats.get(options["audio_format_label"], {})
        mode = options["mode"]
        output_template = os.path.join(options["output_path"], f"{user_facing_title}.%(ext)s")
        
        # 🔧 PASO 1: Determinar los format_ids correctos
        video_format_id = video_format_info.get('format_id')
        audio_format_id = audio_format_info.get('format_id')
        
        # 🔧 PASO 2: Si es combinado multiidioma
        if hasattr(self, 'combined_audio_map') and self.combined_audio_map:
            selected_audio_label = options.get("audio_format_label")
            if selected_audio_label in self.combined_audio_map:
                video_format_id = self.combined_audio_map[selected_audio_label]
                print(f"DEBUG: ✅ Reemplazando format_id con variante de idioma: {video_format_id}")
        
        # Detectar formato simple
        total_formats = len(self.video_formats) + len(self.audio_formats)
        is_combined = video_format_info.get('is_combined', False)
        is_simple_format = (total_formats == 1 and (is_combined or not self.audio_formats))

        if is_simple_format and video_format_id:
            protocol_ids = ['http', 'https', 'm3u8', 'm3u8_native', 'hls', 'dash']
            is_simple_id = (
                video_format_id.isdigit() or
                video_format_id in ['default', 'best'] or
                video_format_id in protocol_ids or
                (len(video_format_id) <= 10 and '+' not in video_format_id)
            )
            if not is_simple_id:
                is_simple_format = False
        
        # 🔧 PASO 3: Construir el selector preciso
        precise_selector = ""
        
        if audio_extraction_fallback:
            precise_selector = video_format_id
            
        elif mode == "Video+Audio":
            if is_simple_format and video_format_id:
                precise_selector = video_format_id
            elif is_combined and video_format_id:
                precise_selector = video_format_id
            elif video_format_id and audio_format_id:
                precise_selector = f"{video_format_id}+{audio_format_id}"
                
        elif mode == "Solo Audio":
            precise_selector = audio_format_id
        
        print(f"DEBUG: 📌 Selector de formato: {precise_selector}")
        
        # 🔧 PASO 4: Configurar yt-dlp base
        if getattr(sys, 'frozen', False):
            project_root = os.path.dirname(sys.executable)
        else:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
        ydl_opts = {
            'outtmpl': output_template,
            'format': precise_selector,
            'postprocessors': [],
            'noplaylist': True,
            'ffmpeg_location': self.ffmpeg_processor.ffmpeg_path,
            'retries': 2,
            'fragment_retries': 2,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'referer': options["url"],
        }
        
        # 🆕 CORRECCIÓN CRÍTICA: Manejo correcto de fragmentos
        want_fragment = options.get("fragment_enabled") and (options.get("start_time") or options.get("end_time"))
        force_full = options.get("force_full_download", False)
        keep_full = options.get("keep_original_on_clip", False) # <--- NUEVO
        
        # Lógica Maestra:
        # Usamos el modo fragmento de YT-DLP (descarga parcial) SOLO SI:
        # 1. El usuario quiere un fragmento.
        # 2. NO forzó la descarga completa (Modo Rápido).
        # 3. NO quiere conservar el original (porque necesitamos bajarlo todo para conservarlo).
        is_fragment_mode = want_fragment and not force_full and not keep_full

        if is_fragment_mode:
            start_time_str = options.get("start_time") or ""  # 🆕 Puede estar vacío
            end_time_str = options.get("end_time") or ""      # 🆕 Puede estar vacío
            
            # 🆕 VALIDACIÓN: Al menos uno debe estar definido
            if not start_time_str and not end_time_str:
                print("DEBUG: ⚠️ Modo fragmento activado pero sin tiempos definidos")
                is_fragment_mode = False
            else:
                # Convertir tiempos a segundos (usar 0 si está vacío el inicio)
                start_seconds = self.time_str_to_seconds(start_time_str) if start_time_str else 0
                
                # Usar None si no hay tiempo final (significa "hasta el final")
                end_seconds = self.time_str_to_seconds(end_time_str) if end_time_str else None
                
                print(f"DEBUG: 🎬 Configurando descarga de fragmento:")
                print(f"  - Inicio: {start_time_str if start_time_str else '00:00:00 (desde el principio)'} ({start_seconds}s)")
                
                if end_seconds is not None:
                    print(f"  - Fin: {end_time_str} ({end_seconds}s)")
                else:
                    print(f"  - Fin: (hasta el final del video)")
                
                # La API correcta de yt-dlp para rangos de descarga
                try:
                    from yt_dlp.utils import download_range_func
                    
                    # Crear el rango con SEGUNDOS (int/float), no strings
                    if end_seconds is not None:
                        ranges = [(start_seconds, end_seconds)]
                    else:
                        ranges = [(start_seconds, float('inf'))]  # Hasta el infinito = hasta el final
                    
                    ydl_opts['download_ranges'] = download_range_func(None, ranges)
                    
                    # --- MODIFICACIÓN: Usar el checkbox ---
                    use_precise = options.get("precise_clip_enabled", False)
                    ydl_opts['force_keyframes_at_cuts'] = use_precise
                    
                    print(f"DEBUG: ✅ download_ranges configurado: {ranges} | Preciso: {use_precise}")
                    
                except Exception as e:
                    print(f"DEBUG: ⚠️ Error configurando download_ranges: {e}")
                    print(f"DEBUG: 🔥 Fallback: se descargará completo y se cortará con FFmpeg")
                    is_fragment_mode = False
                
                # 🆕 LOGGING: Comando CLI actualizado
                if end_time_str:
                    download_section = f"*{start_time_str if start_time_str else '0'}-{end_time_str}"
                else:
                    download_section = f"*{start_time_str if start_time_str else '0'}-inf"
            
            # Construir string de flag
            force_keyframe_flag = "--force-keyframes-at-cuts" if options.get("precise_clip_enabled") else ""
            
            cli_command = f"yt-dlp -f \"{precise_selector}\" --download-sections \"{download_section}\" {force_keyframe_flag} \"{options['url']}\" -o \"{output_template}\""
            
            print(f"\n{'='*80}")
            print(f"🔍 COMANDO EQUIVALENTE DE CLI:")
            print(f"{cli_command}")
            print(f"{'='*80}\n")
        
        # Resto de configuración (subtítulos, cookies, etc.)
        if mode == "Solo Audio" and audio_format_info.get('extract_only'):
            ydl_opts['postprocessors'].append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            })
        
        if options["download_subtitles"] and options.get("selected_subtitle_info"):
            subtitle_info = options["selected_subtitle_info"]
            if subtitle_info:
                should_convert_to_srt = self.clean_subtitle_check.winfo_ismapped() and self.clean_subtitle_check.get() == 1
                
                ydl_opts.update({
                    'writesubtitles': True,
                    'subtitleslangs': [subtitle_info['lang']],
                    'writeautomaticsub': subtitle_info.get('automatic', False),
                    'embedsubtitles': mode == "Video+Audio"
                })
                
                if should_convert_to_srt:
                    ydl_opts['subtitlesformat'] = 'best/vtt/best'
                    ydl_opts['convertsubtitles'] = 'srt'
                else:
                    ydl_opts['subtitlesformat'] = subtitle_info.get('ext', 'best')
        
        if options["speed_limit"]:
            try: 
                ydl_opts['ratelimit'] = float(options["speed_limit"]) * 1024 * 1024
            except ValueError: 
                pass
        
        cookie_mode = options["cookie_mode"]
        if cookie_mode == "Archivo Manual..." and options["cookie_path"]: 
            ydl_opts['cookiefile'] = options["cookie_path"]
        elif cookie_mode != "No usar":
            browser_arg = options["selected_browser"]
            if options["browser_profile"]: 
                browser_arg += f":{options['browser_profile']}"
            ydl_opts['cookiesfrombrowser'] = (browser_arg,)
        
        # 🆕 Logging detallado de opciones
        print(f"DEBUG: 📋 Opciones de yt-dlp:")
        important_opts = ['format', 'download_ranges', 'force_keyframes_at_cuts', 'postprocessors']
        for key in important_opts:
            if key in ydl_opts:
                print(f"  - {key}: {ydl_opts[key]}")
        
        # 🔧 INTENTOS DE DESCARGA
        if audio_extraction_fallback:
            print(f"DEBUG: [FALLBACK] Descargando video: {precise_selector}")
            downloaded_filepath = download_media(options["url"], ydl_opts, self.update_progress, self.cancellation_event)
            temp_video_for_extraction = downloaded_filepath
            return downloaded_filepath, temp_video_for_extraction 
        else:
            try:
                if not precise_selector:
                    raise yt_dlp.utils.DownloadError("Selector preciso no válido")
                
                print(f"DEBUG: 🚀 INTENTO 1: Descargando con yt-dlp...")
                
                # 🆕 Si es modo fragmento, intentar descarga directa
                if is_fragment_mode:
                    try:
                        print(f"DEBUG: 🎬 Intentando descarga directa de fragmento")
                        downloaded_filepath = download_media(options["url"], ydl_opts, self.update_progress, self.cancellation_event)
                        print(f"DEBUG: ✅ Fragmento descargado: {downloaded_filepath}")
                        
                        # Desactivar recorte post-descarga
                        options["fragment_enabled"] = False
                        options["start_time"] = ""
                        options["end_time"] = ""
                        
                        return downloaded_filepath, temp_video_for_extraction
                        
                    except Exception as fragment_error:
                        # ✅ NUEVO: Detectar si fue una cancelación
                        # Verificamos si el evento está activo O si el mensaje de error dice "cancelada"
                        is_cancellation = self.cancellation_event.is_set() or "cancelada" in str(fragment_error).lower()
                        
                        if is_cancellation:
                            print("DEBUG: 🛑 Cancelación detectada en fragmento. Abortando sin diálogo de fallback.")
                            raise UserCancelledError("Descarga cancelada por el usuario.")

                        # Si NO fue cancelación, es un error real -> Mostrar diálogo
                        print(f"DEBUG: ❌ Error en descarga de fragmento: {fragment_error}")
                        print(f"DEBUG: 🔍 Tipo de error: {type(fragment_error).__name__}")
                        
                        # 🆕 Preguntar al usuario
                        self.app.ui_request_data = {
                            "type": "ask_yes_no",
                            "title": "Descarga de Fragmento Fallida",
                            "message": (
                                f"No se pudo descargar el fragmento directamente.\n\n"
                                f"Error: {str(fragment_error)[:100]}\n\n"
                                f"¿Deseas descargar el video completo y luego cortarlo?\n\n"
                                f"(Esto tomará más tiempo y espacio en disco)"
                            )
                        }
                        self.app.ui_response_event.clear()
                        self.app.ui_request_event.set()
                        self.app.ui_response_event.wait()
                        
                        user_choice = self.app.ui_response_data.get("result", False)
                        
                        if not user_choice:
                            raise UserCancelledError("El usuario canceló la descarga del video completo.")
                        
                        # Usuario aceptó: descargar completo
                        print(f"DEBUG: 📥 Descargando video completo para cortar después...")
                        ydl_opts_full = ydl_opts.copy()
                        ydl_opts_full.pop('download_ranges', None)
                        ydl_opts_full.pop('force_keyframes_at_cuts', None)
                        ydl_opts_full.pop('_fragment_range', None)
                        
                        # Limpiar postprocessors relacionados con fragmentos
                        ydl_opts_full['postprocessors'] = [
                            pp for pp in ydl_opts_full.get('postprocessors', [])
                            if pp.get('key') != 'FFmpegVideoRemuxer'
                        ]
                        
                        options["fragment_enabled"] = True  # Mantener para corte con FFmpeg
                        
                        downloaded_filepath = download_media(options["url"], ydl_opts_full, self.update_progress, self.cancellation_event)
                else:
                    # Descarga normal sin fragmento
                    downloaded_filepath = download_media(options["url"], ydl_opts, self.update_progress, self.cancellation_event)
                
            except yt_dlp.utils.DownloadError as e:
                print(f"DEBUG: Falló el intento 1. Error: {e}")
                print("DEBUG: Pasando al Paso 2 (selector flexible).")
                
                try:
                    # INTENTO 2 MEJORADO: Lógica adaptativa
                    if is_simple_format:
                        strict_flexible_selector = 'best'
                        print(f"DEBUG: INTENTO 2 (simple): Usando selector 'best'")
                    
                    elif 'twitter' in options["url"] or 'x.com' in options["url"]:
                        strict_flexible_selector = 'best'
                        print(f"DEBUG: INTENTO 2 (Twitter): Usando selector 'best'")
                        
                    elif not self.video_formats and not self.audio_formats:
                        strict_flexible_selector = 'best'
                        
                    else:
                        info_dict = self.analysis_cache.get(options["url"], {}).get('data', {})
                        selected_audio_details = next((f for f in info_dict.get('formats', []) if f.get('format_id') == audio_format_id), None)
                        language_code = selected_audio_details.get('language') if selected_audio_details else None
                        
                        strict_flexible_selector = ""
                        if self.has_audio_streams:
                            if mode == "Video+Audio":
                                height = video_format_info.get('height')
                                video_selector = f'bv[height={height}]' if height else 'bv' 
                                audio_selector = f'ba[lang={language_code}]' if language_code else 'ba'
                                strict_flexible_selector = f'{video_selector}+{audio_selector}'
                            elif mode == "Solo Audio":
                                strict_flexible_selector = f'ba[lang={language_code}]' if language_code else 'ba'
                        else: 
                            height = video_format_info.get('height')
                            strict_flexible_selector = f'bv[height={height}]' if height else 'bv'
                    
                    ydl_opts['format'] = strict_flexible_selector
                    print(f"DEBUG: INTENTO 2: Descargando con selector flexible: {strict_flexible_selector}")
                    downloaded_filepath = download_media(options["url"], ydl_opts, self.update_progress, self.cancellation_event)
                    
                except yt_dlp.utils.DownloadError:
                    print("DEBUG: Falló intento 2. Pasando al Paso 3 (compromiso).")

                    details_ready_event = threading.Event()
                    compromise_details = {"text": "Obteniendo detalles..."}
                    def get_details_thread():
                        compromise_details["text"] = self.app._get_best_available_info(options["url"], options)
                        details_ready_event.set() 
                    self.app.after(0, self.update_progress, 50, "Calidad no disponible. Obteniendo detalles de alternativa...")
                    threading.Thread(target=get_details_thread, daemon=True).start()
                    details_ready_event.wait() 
                    self.app.ui_request_data = {"type": "ask_compromise", "details": compromise_details["text"]}
                    self.app.ui_response_event.clear()
                    self.app.ui_request_event.set()
                    self.app.ui_response_event.wait()
                    user_choice = self.app.ui_response_data.get("result", "cancel")
                    if user_choice == "accept":
                        print("DEBUG: PASO 4: El usuario aceptó. Intentando con selector final.")
                        if not self.video_formats and not self.audio_formats:
                            final_selector = 'best'
                        else:
                            final_selector = 'ba'
                            if mode == "Video+Audio":
                                final_selector = 'bv+ba' if self.has_audio_streams else 'bv'
                        ydl_opts['format'] = final_selector
                        downloaded_filepath = download_media(options["url"], ydl_opts, self.update_progress, self.cancellation_event)
                    else:
                        raise UserCancelledError("Descarga cancelada por el usuario en el diálogo de compromiso.")
            except Exception as final_e:
                print(f"DEBUG: ❌ Error inesperado: {final_e}")
                raise
                
            if not downloaded_filepath or not os.path.exists(downloaded_filepath):
                raise Exception("La descarga falló o el archivo no se encontró.")
            
            return downloaded_filepath, temp_video_for_extraction

    def _perform_cleanup(self, process_successful, recode_phase_started, final_recoded_path, 
                     temp_video_for_extraction, backup_file_path, cleanup_required, 
                     user_facing_title, options, keep_file_on_cancel, downloaded_filepath):
        """Esta función se encargará de TODA la limpieza del bloque 'finally'."""

        if not process_successful and not self.local_file_path:
            output_dir = options.get("output_path", "")

            if output_dir and user_facing_title:
                base_title_for_cleanup = user_facing_title.replace("_recoded", "")
                
                # 🆕 Limpieza inmediata
                self._cleanup_ytdlp_temp_files(output_dir, base_title_for_cleanup)
                
                # 🆕 Programar limpieza diferida para archivos bloqueados
                def deferred_cleanup():
                    time.sleep(3)  # Esperar 3 segundos
                    print("DEBUG: Ejecutando limpieza diferida...")
                    self._cleanup_ytdlp_temp_files(output_dir, base_title_for_cleanup)
                
                threading.Thread(target=deferred_cleanup, daemon=True).start()

            if recode_phase_started and final_recoded_path and os.path.exists(final_recoded_path):
                try:
                    gc.collect()
                    time.sleep(0.5) 
                    print(f"DEBUG: Limpiando archivo de recodificación temporal por fallo (Modo URL): {final_recoded_path}")
                    os.remove(final_recoded_path)
                except OSError as e:
                    print(f"ERROR: No se pudo limpiar el archivo de recodificación temporal (Modo URL): {e}")
            if temp_video_for_extraction and os.path.exists(temp_video_for_extraction):
                try:
                    print(f"DEBUG: Limpiando video temporal por fallo (Modo URL): {temp_video_for_extraction}")
                    os.remove(temp_video_for_extraction)
                except OSError as e:
                    print(f"ERROR: No se pudo limpiar el video temporal (Modo URL): {e}")
            if backup_file_path and os.path.exists(backup_file_path):
                print("AVISO: La descarga falló. Restaurando el archivo original desde el respaldo (Modo URL).")
                try:
                    original_path = backup_file_path.removesuffix(".bak")
                    if os.path.exists(original_path) and os.path.normpath(original_path) != os.path.normpath(backup_file_path):
                        os.remove(original_path)
                    os.rename(backup_file_path, original_path)
                    print(f"ÉXITO: Respaldo restaurado a: {original_path}")
                except OSError as err:
                    print(f"ERROR CRÍTICO: No se pudo restaurar el respaldo: {err}")
            elif cleanup_required:
                print("DEBUG: Iniciando limpieza general por fallo de operación.")
                try:
                    gc.collect()
                    time.sleep(1) 
                    base_title_for_cleanup = user_facing_title.replace("_recoded", "")
                    for filename in os.listdir(options["output_path"]):
                        if not filename.startswith(base_title_for_cleanup):
                            continue
                        file_path_to_check = os.path.join(options["output_path"], filename)
                        should_preserve = False
                        known_sidecar_exts = ('.srt', '.vtt', '.ass', '.ssa', '.json3', '.srv1', '.srv2', '.srv3', '.ttml', '.smi', '.tml', '.lrc', '.xml', '.jpg', '.jpeg', '.png')                            
                        if keep_file_on_cancel:
                            normalized_preserved_path = os.path.normpath(keep_file_on_cancel)
                            if os.path.normpath(file_path_to_check) == normalized_preserved_path:
                                should_preserve = True
                            else:
                                base_preserved_name = os.path.splitext(os.path.basename(keep_file_on_cancel))[0]
                                if filename.startswith(base_preserved_name) and filename.lower().endswith(known_sidecar_exts):
                                    should_preserve = True                            
                        elif options.get("keep_original_file", False) and downloaded_filepath:
                            normalized_original_path = os.path.normpath(downloaded_filepath)
                            if os.path.normpath(file_path_to_check) == normalized_original_path:
                                should_preserve = True
                            else:
                                base_original_name = os.path.splitext(os.path.basename(downloaded_filepath))[0]
                                if filename.startswith(base_original_name) and filename.lower().endswith(known_sidecar_exts):
                                    should_preserve = True
                        if should_preserve:
                            print(f"DEBUG: Conservando archivo solicitado o asociado: {file_path_to_check}")
                            continue
                        else:
                            print(f"DEBUG: Eliminando archivo no deseado: {file_path_to_check}")
                            os.remove(file_path_to_check)
                            
                except Exception as cleanup_e:
                    print(f"ERROR: Falló el proceso de limpieza de archivos: {cleanup_e}")
        elif process_successful and backup_file_path and os.path.exists(backup_file_path):
            try:
                os.remove(backup_file_path)
                print("DEBUG: Proceso exitoso, respaldo eliminado.")
            except OSError as err:
                print(f"AVISO: No se pudo eliminar el archivo de respaldo: {err}")
        self.active_subprocess_pid = None
        self.active_operation_thread = None

    def _cleanup_ytdlp_temp_files(self, output_dir, base_title):
        """
        Limpia archivos temporales específicos de yt-dlp (.part, fragmentos, etc.)
        Incluye reintentos y manejo de bloqueos de archivo.
        """
        import glob
        
        patterns_to_clean = [
            f"{base_title}*.part",           # Archivos parciales
            f"{base_title}*.f[0-9]*",        # Fragmentos de formato
            f"{base_title}*.ytdl",           # Archivos de metadata
            f"{base_title}*.temp",           # Temporales genéricos
            f"*.f[0-9]*.part",               # Fragmentos parciales sin título
            # 🆕 Patrones adicionales comunes
            f"{base_title}*.temp.*",
            f"{base_title}*.part-*",
            f".{base_title}*",               # Archivos ocultos temporales
        ]
        
        cleaned_count = 0
        failed_files = []
        
        for pattern in patterns_to_clean:
            full_pattern = os.path.join(output_dir, pattern)
            
            for temp_file in glob.glob(full_pattern):
                if not os.path.exists(temp_file):
                    continue
                
                # 🆕 Reintentos con espera para archivos bloqueados
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # 🆕 Liberar recursos antes de eliminar
                        gc.collect()
                        
                        # 🆕 Espera progresiva en cada intento
                        if attempt > 0:
                            wait_time = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                            time.sleep(wait_time)
                        
                        os.remove(temp_file)
                        print(f"DEBUG: Eliminado temp de yt-dlp: {temp_file}")
                        cleaned_count += 1
                        break  # Éxito, salir del loop de reintentos
                        
                    except PermissionError as e:
                        if attempt < max_retries - 1:
                            print(f"⚠️ Archivo bloqueado, reintentando ({attempt+1}/{max_retries}): {temp_file}")
                            continue
                        else:
                            print(f"⚠️ No se pudo eliminar (bloqueado): {temp_file}")
                            failed_files.append(temp_file)
                            
                    except OSError as e:
                        if attempt < max_retries - 1:
                            continue
                        else:
                            print(f"⚠️ No se pudo eliminar {temp_file}: {e}")
                            failed_files.append(temp_file)
        
        if cleaned_count > 0:
            print(f"DEBUG: Se eliminaron {cleaned_count} archivos temporales de yt-dlp")
        
        # 🆕 Reportar archivos que no se pudieron eliminar
        if failed_files:
            print(f"⚠️ {len(failed_files)} archivo(s) temporal(es) no se pudieron eliminar:")
            for f in failed_files:
                print(f"   - {os.path.basename(f)}")
            
            # 🆕 Intentar una última vez después de un delay mayor
            time.sleep(2)
            remaining_files = []
            
            for temp_file in failed_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        print(f"✅ Eliminado en reintento final: {os.path.basename(temp_file)}")
                        cleaned_count += 1
                except Exception as e:
                    remaining_files.append(temp_file)
            
            if remaining_files:
                print(f"⚠️ {len(remaining_files)} archivo(s) requieren limpieza manual:")
                for f in remaining_files:
                    print(f"   - {f}")

    def _reset_buttons_to_original_state(self):
        """ Restablece los botones a su estado original, aplicando el color correcto. """
        self.analyze_button.configure(
            text=self.original_analyze_text,
            fg_color=self.original_analyze_fg_color,
            command=self.original_analyze_command,
            state="normal"
        )

        if self.local_file_path:
            button_text = "Iniciar Proceso"
            button_color = self.PROCESS_BTN_COLOR
        else:
            button_text = self.original_download_text
            button_color = self.DOWNLOAD_BTN_COLOR

        hover_color = self.PROCESS_BTN_HOVER if self.local_file_path else self.DOWNLOAD_BTN_HOVER

        self.download_button.configure(
            text=button_text,
            fg_color=button_color,
            hover_color=hover_color,
            command=self.original_download_command
        )

        self.toggle_manual_subtitle_button()
        self.update_download_button_state()

    def _save_thumbnail_if_enabled(self, base_filepath):
        """Guarda la miniatura si la opción está activada, usando la ruta del archivo base."""
        if self.auto_save_thumbnail_check.get() == 1 and self.pil_image and base_filepath:
            try:
                self.app.after(0, self.update_progress, 98, "Guardando miniatura...")
                
                # 🆕 Validar que base_filepath sea un archivo válido
                if not os.path.exists(base_filepath):
                    print(f"ADVERTENCIA: No se puede guardar miniatura, archivo no encontrado: {base_filepath}")
                    return None
                
                # 🆕 Si es una carpeta (modo extraer), no guardar miniatura
                if os.path.isdir(base_filepath):
                    print("DEBUG: Saltando guardado de miniatura (resultado es una carpeta)")
                    return None
                
                output_directory = os.path.dirname(base_filepath)
                clean_title = os.path.splitext(os.path.basename(base_filepath))[0]
                
                # Limpiar sufijos comunes
                if clean_title.endswith("_recoded"):
                    clean_title = clean_title.rsplit('_recoded', 1)[0]
                if clean_title.endswith("_fragmento"):
                    clean_title = clean_title.rsplit('_fragmento', 1)[0]
                
                thumb_path = os.path.join(output_directory, f"{clean_title}.jpg")
                self.pil_image.convert("RGB").save(thumb_path, quality=95)
                print(f"DEBUG: Miniatura guardada automáticamente en {thumb_path}")
                return thumb_path
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo guardar la miniatura automáticamente: {e}")
        return None

    def on_process_finished(self, success, message, final_filepath, show_dialog=True):
        """
        Callback UNIFICADO. Usa las listas de extensiones de la clase para una clasificación robusta.
        """
        if success and final_filepath and self.app.ACTIVE_TARGET_SID_accessor():
            with self.app.LATEST_FILE_LOCK:
                file_package = {
                    "video": None,
                    "thumbnail": None,
                    "subtitle": None
                }
                file_ext_without_dot = os.path.splitext(final_filepath)[1].lower().lstrip('.')
                if file_ext_without_dot in VIDEO_EXTENSIONS or file_ext_without_dot in AUDIO_EXTENSIONS or file_ext_without_dot in SINGLE_STREAM_AUDIO_CONTAINERS:
                    file_package["video"] = final_filepath.replace('\\', '/')
                elif file_ext_without_dot == 'srt':
                    file_package["subtitle"] = final_filepath.replace('\\', '/')
                elif file_ext_without_dot == 'jpg':
                     file_package["thumbnail"] = final_filepath.replace('\\', '/')
                if file_package["video"]:
                    output_dir = os.path.dirname(final_filepath)
                    base_name = os.path.splitext(os.path.basename(final_filepath))[0]
                    if base_name.endswith('_recoded'):
                        base_name = base_name.rsplit('_recoded', 1)[0]
                    expected_thumb_path = os.path.join(output_dir, f"{base_name}.jpg")
                    if os.path.exists(expected_thumb_path):
                        file_package["thumbnail"] = expected_thumb_path.replace('\\', '/')
                    for item in os.listdir(output_dir):
                        if item.startswith(base_name) and item.lower().endswith('.srt'):
                             file_package["subtitle"] = os.path.join(output_dir, item).replace('\\', '/')
                             break
                print(f"INFO: Paquete de archivos listo para enviar: {file_package}")
                self.app.socketio.emit('new_file', {'filePackage': file_package}, to=self.app.ACTIVE_TARGET_SID_accessor())
        self.last_download_path = final_filepath
        self.progress_bar.stop()
        self.progress_bar.set(1 if success else 0)
        final_message = self._clean_ansi_codes(message)
        if success:
            self.progress_label.configure(text=final_message)
            if final_filepath:
                # --- NUEVA LÓGICA DE VISIBILIDAD DE BOTÓN ---
                if os.path.isdir(final_filepath):
                    # ¡Es una carpeta! (Resultado de Extracción)
                    print(f"DEBUG: Proceso finalizado. Resultado: carpeta de frames. Ruta: {final_filepath}")
                    
                    # ✅ Mostrar mensaje de éxito y habilitar botón
                    if hasattr(self, 'extract_success_label'):
                        self.extract_success_label.configure(text="✅ Extracción completada")
                    if hasattr(self, 'send_to_imagetools_button'):
                        self.send_to_imagetools_button.configure(state="normal")
                    
                    # ✅ El botón 📂 abre la carpeta CONTENEDORA de la carpeta de frames
                    self.open_folder_button.configure(state="normal")

                elif os.path.isfile(final_filepath):
                    # Es un archivo (Descarga/Recodificación normal)
                    print(f"DEBUG: Proceso finalizado. Resultado: archivo. Ruta: {final_filepath}")
                    
                    # ✅ Ocultar mensaje y deshabilitar botón
                    if hasattr(self, 'extract_success_label'):
                        self.extract_success_label.configure(text="")
                    if hasattr(self, 'send_to_imagetools_button'):
                        self.send_to_imagetools_button.configure(state="disabled")
                    
                    # ✅ El botón 📂 abre la carpeta contenedora del archivo
                    self.open_folder_button.configure(state="normal")

                else:
                    # ✅ Caso por defecto: deshabilitar todo
                    self.open_folder_button.configure(state="disabled")
                    if hasattr(self, 'extract_success_label'):
                        self.extract_success_label.configure(text="")
                    if hasattr(self, 'send_to_imagetools_button'):
                        self.send_to_imagetools_button.configure(state="disabled")
                # --- FIN DE LA NUEVA LÓGICA ---
        else:
            if show_dialog:
                self.progress_label.configure(text="❌ Error en la operación. Ver detalles.")
                lowered_message = final_message.lower()
                dialog_message = final_message 
                if "timed out" in lowered_message or "timeout" in lowered_message:
                    dialog_message = ("Falló la conexión (Timeout).\n\n"
                                    "Causas probables:\n"
                                    "• Conexión a internet lenta o inestable.\n"
                                    "• Un antivirus o firewall está bloqueando la aplicación.")
                elif "429" in lowered_message or "too many requests" in lowered_message:
                    dialog_message = (
                        "Demasiadas Peticiones (Error 429).\n\n"
                        "Has realizado demasiadas solicitudes en poco tiempo.\n\n"
                        "**Sugerencias:**\n"
                        "1. Desactiva la descarga automática de subtítulos y miniaturas.\n"
                        "2. Usa la opción de 'Cookies' si el problema persiste.\n"
                        "3. Espera unos minutos antes de volver a intentarlo."
                    )
                elif any(keyword in lowered_message for keyword in ["age-restricted", "login required", "sign in", "private video", "premium", "members only"]):
                    dialog_message = (
                        "La descarga falló. El contenido parece ser privado, tener restricción de edad o requerir una suscripción.\n\n"
                        "Por favor, intenta configurar las 'Cookies' en la aplicación y vuelve a analizar la URL."
                    )
                elif "cannot parse data" in lowered_message and "facebook" in lowered_message:
                    dialog_message = (
                        "Falló el análisis de Facebook.\n\n"
                        "Este error usualmente ocurre con videos privados o con restricción de edad. "
                        "Intenta configurar las 'Cookies' para solucionarlo."
                    )
                elif "ffmpeg not found" in lowered_message:
                    dialog_message = (
                        "Error Crítico: FFmpeg no encontrado.\n\n"
                        "yt-dlp necesita FFmpeg para realizar la conversión de subtítulos.\n\n"
                        "Asegúrate de que FFmpeg esté correctamente instalado en la carpeta 'bin' de la aplicación."
                    )

                dialog = SimpleMessageDialog(self.app, "Error en la Operación", dialog_message)
                self.app.wait_window(dialog)
            else:
                 self.progress_label.configure(text=final_message)

            self.open_folder_button.configure(state="disabled")
            self.send_to_imagetools_button.pack_forget()

        self._reset_buttons_to_original_state()
    
    def _predict_final_extension(self, video_info, audio_info, mode):
        """
        Predice la extensión de archivo más probable que yt-dlp usará
        al fusionar los streams de video y audio seleccionados.
        """

        if mode == "Solo Audio":
            return f".{audio_info.get('ext', 'mp3')}"

        if video_info.get('is_combined'):
            return f".{video_info.get('ext', 'mp4')}"

        v_ext = video_info.get('ext')
        a_ext = audio_info.get('ext')
        
        if not a_ext or a_ext == 'none':
            return f".{v_ext}" if v_ext else ".mp4"

        if v_ext == 'mp4' and a_ext in ['m4a', 'mp4']:
            return ".mp4"

        if v_ext == 'webm' and a_ext in ['webm', 'opus']:
            return ".webm"

        return ".mkv"

    def _resolve_output_path(self, desired_filepath):
        """
        Comprueba si una ruta de archivo deseada existe. Si existe,
        lanza el diálogo de conflicto y maneja la lógica de
        sobrescribir, renombrar o cancelar.
        
        Esta función está diseñada para ser llamada desde un HILO SECUNDARIO.
        
        Args:
            desired_filepath (str): La ruta completa del archivo que se
                                    pretende crear.
        
        Returns:
            tuple (str, str or None):
                - final_path: La ruta segura y final donde se debe escribir 
                              el archivo (podría ser la original o una renombrada).
                - backup_path: La ruta a un archivo .bak si se eligió 
                               "sobrescribir", o None si no.
        
        Raises:
            UserCancelledError: Si el usuario presiona "Cancelar" en el diálogo.
            Exception: Si falla el renombrado del archivo de respaldo.
        """
        final_path = desired_filepath
        backup_path = None

        if not os.path.exists(final_path):
            # Caso ideal: no hay conflicto, devuelve la ruta deseada.
            return final_path, backup_path

        # --- Hay un conflicto, pedir intervención de la UI ---
        print(f"DEBUG: Conflicto de archivo detectado en: {final_path}")
        self.app.ui_request_data = {
            "type": "ask_conflict", 
            "filename": os.path.basename(final_path)
        }
        self.app.ui_response_event.clear()
        self.app.ui_request_event.set()
        
        # Pausa este hilo de trabajo hasta que la UI (hilo principal) responda
        self.app.ui_response_event.wait()
        
        user_choice = self.app.ui_response_data.get("result", "cancel")

        if user_choice == "cancel":
            raise UserCancelledError("Operación cancelada por el usuario en conflicto de archivo.")
        
        elif user_choice == "overwrite":
            print(f"DEBUG: Usuario eligió sobrescribir. Creando backup de {final_path}")
            try:
                backup_path = final_path + ".bak"
                if os.path.exists(backup_path): 
                    os.remove(backup_path)
                os.rename(final_path, backup_path)
            except OSError as e:
                raise Exception(f"No se pudo respaldar el archivo original: {e}")
            # final_path sigue siendo la ruta deseada.
        
        elif user_choice == "rename":
            print("DEBUG: Usuario eligió renombrar. Buscando un nuevo nombre...")
            base, ext = os.path.splitext(final_path)
            counter = 1
            while True:
                new_path_candidate = f"{base} ({counter}){ext}"
                if not os.path.exists(new_path_candidate):
                    final_path = new_path_candidate
                    print(f"DEBUG: Nuevo nombre encontrado: {final_path}")
                    break
                counter += 1
        
        return final_path, backup_path

    def update_progress(self, percentage, message):
        """
        Actualiza la barra de progreso. AHORA es inteligente y acepta:
        - Valores en escala 0-100 (de descargas/recodificación)
        - Valores en escala 0.0-1.0
        - Valor especial -1 para activar modo INDETERMINADO
        """
        try:
            progress_value = float(percentage)
        except (ValueError, TypeError):
            progress_value = 0.0

        # 🆕 NUEVO: Detectar modo indeterminado
        if progress_value == -1:
            def _update():
                self.progress_bar.configure(mode="indeterminate")
                self.progress_bar.start()  # Inicia animación
                self.progress_label.configure(text=message)
            self.app.after(0, _update)
            return

        # Normalizar valores normales
        if progress_value > 1.0:
            progress_value = progress_value / 100.0

        capped_percentage = max(0.0, min(progress_value, 1.0))
        
        def _update():
            # 🆕 Volver a modo determinado si estaba en indeterminado
            if self.progress_bar.cget("mode") == "indeterminate":
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")
            
            self.progress_bar.set(capped_percentage)
            self.progress_label.configure(text=message)
            
        self.app.after(0, _update)

    def start_analysis_thread(self, event=None):
        self.analysis_is_complete = False
        url = self.url_entry.get()
        if url and self.local_file_path:
            self.reset_to_url_mode()
            self.url_entry.insert(0, url)
        if self.analyze_button.cget("text") == "Cancelar":
            return
        if not url:
            return
        if url in self.analysis_cache:
            cached_entry = self.analysis_cache[url]
            if (time.time() - cached_entry['timestamp']) < self.CACHE_TTL:
                print("DEBUG: Resultado encontrado en caché. Cargando...")
                self.update_progress(100, "Resultado encontrado en caché. Cargando...")
                self.on_analysis_complete(cached_entry['data'])
                return
        self.analyze_button.configure(text="Cancelar", fg_color=self.CANCEL_BTN_COLOR, hover_color=self.CANCEL_BTN_HOVER, command=self.cancel_operation)
        self.download_button.configure(state="disabled") 
        self.open_folder_button.configure(state="disabled")
        self.save_subtitle_button.configure(state="disabled") 
        self.cancellation_event.clear()
        self.progress_label.configure(text="Analizando...") 
        self.progress_bar.start() 
        self.create_placeholder_label("Analizando...")
        self.title_entry.delete(0, 'end')
        self.title_entry.insert(0, "Analizando...")
        self.video_quality_menu.configure(state="disabled", values=["-"])
        self.audio_quality_menu.configure(state="disabled", values=["-"])
        self.subtitle_lang_menu.configure(state="disabled", values=["-"])
        self.subtitle_lang_menu.set("-")
        self.subtitle_type_menu.configure(state="disabled", values=["-"])
        self.subtitle_type_menu.set("-") 
        self.toggle_manual_subtitle_button() 
        self.analysis_was_playlist = False
        threading.Thread(target=self._run_analysis_subprocess, args=(url,), daemon=True).start()

    def _run_analysis_subprocess(self, url):
        """
        Ejecuta el análisis usando la API de yt-dlp y captura la salida de texto
        para preservar la lógica de análisis de subtítulos.
        """
        try:
            self.app.after(0, self.update_progress, 0, "Iniciando análisis de URL...")

            ydl_opts = {
                'no_warnings': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'referer': url,
                'noplaylist': True,
                'playlist_items': '1',
                'listsubtitles': True,
                'progress_hooks': [lambda d: self.cancellation_event.is_set() and (_ for _ in ()).throw(UserCancelledError("Análisis cancelado."))],
            }

            cookie_mode = self.cookie_mode_menu.get()
            if cookie_mode == "Archivo Manual..." and self.cookie_path_entry.get():
                ydl_opts['cookiefile'] = self.cookie_path_entry.get()
            elif cookie_mode != "No usar":
                browser_arg = self.browser_var.get()
                profile = self.browser_profile_entry.get()
                if profile:
                    browser_arg += f":{profile}"
                ydl_opts['cookiesfrombrowser'] = (browser_arg,)

            text_capture = io.StringIO()
            info = None

            with redirect_stdout(text_capture):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(url, download=False)
                        if info:
                            info = self._normalize_info_dict(info)

                    except Exception as e:
                        print(f"\nError interno de yt-dlp: {e}")
            
            if self.cancellation_event.is_set():
                raise UserCancelledError("Análisis cancelado por el usuario.")

            captured_text = text_capture.getvalue()
            other_lines = captured_text.strip().splitlines()

            if info is None:
                raise Exception(f"yt-dlp falló: {' '.join(other_lines)}")
            
            formats_raw = info.get('formats', [])
            print(f"\n🔍 DEBUG: Formatos RAW recibidos de yt-dlp: {len(formats_raw)}")
            for idx, f in enumerate(formats_raw):
                print(f"  [{idx}] id={f.get('format_id')}, ext={f.get('ext')}, "
                    f"vcodec={f.get('vcodec')}, acodec={f.get('acodec')}, "
                    f"resolution={f.get('resolution')}")

            if 'subtitles' not in info and 'automatic_captions' not in info:
                info['subtitles'], info['automatic_captions'] = self._parse_subtitle_lines_from_text(other_lines)

            if info.get('is_live'):
                self.app.after(0, lambda: self.on_analysis_complete(None, "AVISO: La URL apunta a una transmisión en vivo."))

                return
                
            self.app.after(0, self.on_analysis_complete, info)

        except UserCancelledError:
            self.app.after(0, lambda: self.on_process_finished(False, "Análisis cancelado.", None, show_dialog=False))
        except Exception as e:
            error_message = f"ERROR: {e}"
            if isinstance(e, yt_dlp.utils.DownloadError):
                error_message = f"ERROR de yt-dlp: {str(e).replace('ERROR:', '').strip()}"
            self.app.after(0, lambda: self.on_analysis_complete(None, error_message))

        finally:
            self.active_subprocess_pid = None

    def _normalize_info_dict(self, info):
        """
        Normaliza el diccionario de info...
        """
        if not info:
            return info

        # ✅ NUEVO: Aplicar reglas específicas de sitios (Twitch, etc.)
        # Esto corregirá los códecs 'unknown' antes de que el resto de la lógica los vea.
        info = apply_site_specific_rules(info)

        formats = info.get('formats', [])
        
        # ✅ CASO 1: Ya tiene formats, retornar tal cual
        if formats:
            return info
        
        # ✅ CASO 2: Detectar si es contenido de audio directo
        url = info.get('url')
        ext = info.get('ext')
        vcodec = info.get('vcodec', 'none')
        acodec = info.get('acodec')
        
        # 🔍 Detectar audio por múltiples señales
        is_audio_content = False
        
        # Señal 1: Codecs explícitos
        if url and ext and (vcodec == 'none' or not vcodec) and acodec and acodec != 'none':
            is_audio_content = True
        
        # Señal 2: Extensión de audio conocida
        elif ext in self.app.AUDIO_EXTENSIONS:
            is_audio_content = True
            if not acodec or acodec == 'none':
                # Inferir codec desde extensión
                acodec = {'mp3': 'mp3', 'opus': 'opus', 'aac': 'aac', 'm4a': 'aac'}.get(ext, ext)
        
        # Señal 3: Extractor conocido de audio
        elif info.get('extractor_key', '').lower() in ['applepodcasts', 'soundcloud', 'audioboom', 'spreaker', 'libsyn']:
            is_audio_content = True
            if not acodec:
                acodec = 'mp3'  # Fallback común
        
        if is_audio_content:
            print(f"DEBUG: 🎵 Contenido de audio directo detectado (ext={ext}, acodec={acodec})")
            
            # Crear un formato sintético
            synthetic_format = {
                'format_id': '0',
                'url': url or info.get('manifest_url') or '',
                'ext': ext or 'mp3',
                'vcodec': 'none',
                'acodec': acodec or 'unknown',
                'abr': info.get('abr'),
                'tbr': info.get('tbr'),
                'filesize': info.get('filesize'),
                'filesize_approx': info.get('filesize_approx'),
                'protocol': info.get('protocol', 'https'),
                'format_note': info.get('format_note', 'Audio directo'),
            }
            
            info['formats'] = [synthetic_format]
            print(f"DEBUG: ✅ Formato sintético creado: {synthetic_format['format_id']}")
        
        # ✅ CASO 3: Livestreams (sin formats pero con manifest_url)
        elif info.get('is_live') and info.get('manifest_url'):
            print(f"DEBUG: 🔴 Livestream detectado sin formats")
            
            synthetic_format = {
                'format_id': 'live',
                'url': info.get('manifest_url'),
                'ext': info.get('ext', 'mp4'),
                'protocol': 'm3u8_native',
                'format_note': 'Livestream',
            }
            
            info['formats'] = [synthetic_format]
        
        return info

    def _parse_subtitle_lines_from_text(self, lines):
        """
        Parsea una lista de líneas de texto (salida de --list-subs) y la convierte
        en diccionarios de subtítulos manuales y automáticos.
        """
        subtitles = {}
        auto_captions = {}
        current_section = None
        for line in lines:
            if "Available subtitles for" in line:
                current_section = 'subs'
                continue
            if "Available automatic captions for" in line:
                current_section = 'auto'
                continue
            if line.startswith("Language") or line.startswith("ID") or line.startswith('---'):
                continue
            parts = re.split(r'\s+', line.strip())
            if len(parts) < 3:
                continue
            lang_code = parts[0]
            formats = [p.strip() for p in parts[1:-1] if p.strip()]
            if current_section == 'subs':
                target_dict = subtitles
            elif current_section == 'auto':
                target_dict = auto_captions
            else:
                continue
            if lang_code not in target_dict:
                target_dict[lang_code] = []
            for fmt in formats:
                target_dict[lang_code].append({
                    'ext': fmt,
                    'url': None, 
                    'name': ''
                })
        return subtitles, auto_captions

    def on_analysis_complete(self, info, error_message=None):
        try:
            if info and info.get('_type') in ('playlist', 'multi_video'):
                self.analysis_was_playlist = True
                if info.get('entries') and len(info['entries']) > 0:
                    print("DEBUG: Playlist detectada. Extrayendo información del primer video.")
                    info = info['entries'][0]
                else:
                    print("DEBUG: Se detectó una playlist vacía o no válida.")
                    error_message = "La URL corresponde a una lista vacía o no válida."
                    info = None
            self.progress_bar.stop()
            if not info or error_message:
                self.analysis_is_complete = False
                self.progress_bar.set(0)
                final_error_message = error_message or "ERROR: No se pudo obtener la información."
                print(f"Error en el análisis de la URL: {final_error_message}")
                self.title_entry.delete(0, 'end')
                self.title_entry.insert(0, final_error_message)
                self.create_placeholder_label("Fallo el análisis")
                self._clear_subtitle_menus()
                return
            self.progress_bar.set(1)
            self.analysis_is_complete = True

            if info:
                extractor = info.get('extractor_key', '').lower()
                
                # Lista de extractors que pueden tener problemas
                problematic_extractors = {
                    'generic': 'Este sitio usa un extractor genérico (puede ser inestable)',
                    'soundcloud': 'SoundCloud detectado (verificando formatos...)',
                    'twitch:stream': 'Livestream de Twitch (sin duración conocida)',
                }
                
                if extractor in problematic_extractors:
                    print(f"ℹ️ INFO: {problematic_extractors[extractor]}")

            url = self.url_entry.get()
            self.analysis_cache[url] = {'data': info, 'timestamp': time.time()}
            print(f"DEBUG: Resultado para '{url}' guardado en caché.")
            if info.get('extractor_key', '').lower().startswith('twitch'):
                print("DEBUG: Detectada URL de Twitch, eliminando datos de rechat y deshabilitando menús.")
                info['subtitles'] = {}
                info['automatic_captions'] = {}
                self._clear_subtitle_menus()
            self.title_entry.delete(0, 'end')
            self.title_entry.insert(0, info.get('title', 'Sin título'))
            self.video_duration = info.get('duration', 0)
            formats = info.get('formats', [])
            self.has_video_streams = any(f.get('height') for f in formats)
            self.has_audio_streams = any(f.get('acodec') != 'none' or (not f.get('height') and f.get('vcodec') == 'none') for f in formats)
            thumbnail_url = info.get('thumbnail')
            if thumbnail_url:
                threading.Thread(target=self.load_thumbnail, args=(thumbnail_url,), daemon=True).start()
            elif self.has_audio_streams and not self.has_video_streams:
                self.create_placeholder_label("🎵", font_size=80)
                self.save_thumbnail_button.configure(state="disabled")
                self.auto_save_thumbnail_check.deselect()
                self.auto_save_thumbnail_check.configure(state="disabled")
            else:
                self.create_placeholder_label("Miniatura")
            self.populate_format_menus(info, self.has_video_streams, self.has_audio_streams)
            self._update_warnings()
            self.update_download_button_state()
            self.update_estimated_size()
            self.update_progress(100, "Análisis completado. ✅ Listo para descargar.")
        finally:
            print("DEBUG: Ejecutando bloque 'finally' de on_analysis_complete para resetear la UI.")
            self._reset_buttons_to_original_state()
            self.toggle_manual_subtitle_button()
            self._validate_recode_compatibility()

    def load_thumbnail(self, path_or_url, is_local=False):
        try:
            # ✅ Limpiar backup
            if hasattr(self, '_original_image_backup'):
                self._original_image_backup = None
                print("DEBUG: Backup de imagen limpiado")
            
            if hasattr(self, '_hover_text_label') and self._hover_text_label is not None:
                try:
                    if self._hover_text_label.winfo_exists():
                        self._hover_text_label.destroy()
                except:
                    pass
                self._hover_text_label = None
            
            self.app.after(0, self.create_placeholder_label, "Cargando miniatura...")
            
            # ✅ MODIFICADO: Cargar imagen según el tipo
            if is_local:
                # Es un archivo local (path)
                with open(path_or_url, 'rb') as f:
                    img_data = f.read()
            else:
                # Es una URL
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://imgur.com/',
                }
                
                max_retries = 2
                timeout = 15
                
                for attempt in range(max_retries):
                    try:
                        response = requests.get(
                            path_or_url, 
                            headers=headers, 
                            timeout=timeout,
                            allow_redirects=True
                        )
                        response.raise_for_status()
                        img_data = response.content
                        break
                        
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 429:
                            if attempt < max_retries - 1:
                                wait_time = 2 ** attempt
                                print(f"⚠️ Rate limit en miniatura. Reintentando en {wait_time}s...")
                                time.sleep(wait_time)
                                continue
                            else:
                                raise Exception(f"Rate limit de Imgur (429). La miniatura no está disponible temporalmente.")
                        else:
                            raise
                            
                    except requests.exceptions.Timeout:
                        if attempt < max_retries - 1:
                            print(f"⚠️ Timeout descargando miniatura. Reintentando...")
                            continue
                        else:
                            raise Exception("Timeout al descargar la miniatura")
            
            # ✅ Validar que img_data no esté vacío
            if not img_data or len(img_data) < 100:
                raise Exception("La miniatura descargada está vacía o corrupta")
            
            # ✅ CRÍTICO: Asignar self.pil_image SIEMPRE
            self.pil_image = Image.open(BytesIO(img_data))
            display_image = self.pil_image.copy()
            display_image.thumbnail((320, 180), Image.Resampling.LANCZOS)
            ctk_image = ctk.CTkImage(light_image=display_image, dark_image=display_image, size=display_image.size)

            def set_new_image():
                if self.thumbnail_label: 
                    self.thumbnail_label.destroy()
                
                parent_widget = self.dnd_overlay if hasattr(self, 'dnd_overlay') else self.thumbnail_container
                
                self.thumbnail_label = ctk.CTkLabel(parent_widget, text="", image=ctk_image)
                self.thumbnail_label.pack(expand=True)
                self.thumbnail_label.image = ctk_image
                
                # ✅ VERIFICAR que ahora SÍ existe
                print(f"DEBUG: ✅ Miniatura cargada. self.pil_image existe: {self.pil_image is not None}, is_local: {is_local}")
                
                self.save_thumbnail_button.configure(state="normal")
                
                # ✅ NUEVO: También habilitar el botón de enviar a H.I.
                if hasattr(self, 'send_thumbnail_to_imagetools_button'):
                    self.send_thumbnail_to_imagetools_button.configure(state="normal")
                
                self.toggle_manual_thumbnail_button()
                
            self.app.after(0, set_new_image)
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else 'unknown'
            error_msg = f"Error HTTP {status_code}"
            
            if status_code == 429:
                error_msg = "Rate limit (429)"
                placeholder_text = "⏳"
            elif status_code == 404:
                error_msg = "Miniatura no encontrada (404)"
                placeholder_text = "❌"
            elif status_code in [403, 401]:
                error_msg = f"Acceso denegado ({status_code})"
                placeholder_text = "🔒"
            else:
                placeholder_text = "❌"
            
            print(f"⚠️ Error al cargar miniatura: {error_msg} - URL: {path_or_url}")
            self.app.after(0, self.create_placeholder_label, placeholder_text, font_size=60)
            
        except requests.exceptions.Timeout:
            print(f"⚠️ Timeout al cargar miniatura: {path_or_url}")
            self.app.after(0, self.create_placeholder_label, "⏱️", font_size=60)
            
        except Exception as e:
            print(f"⚠️ Error al cargar miniatura: {e}")
            self.app.after(0, self.create_placeholder_label, "❌", font_size=60)
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else 'unknown'
            error_msg = f"Error HTTP {status_code}"
            
            if status_code == 429:
                error_msg = "Rate limit (429)"
                placeholder_text = "⏳"
            elif status_code == 404:
                error_msg = "Miniatura no encontrada (404)"
                placeholder_text = "❌"
            elif status_code in [403, 401]:
                error_msg = f"Acceso denegado ({status_code})"
                placeholder_text = "🔒"
            else:
                placeholder_text = "❌"
            
            print(f"⚠️ Error al cargar miniatura: {error_msg} - URL: {path_or_url}")
            self.app.after(0, self.create_placeholder_label, placeholder_text, font_size=60)
            
        except requests.exceptions.Timeout:
            print(f"⚠️ Timeout al cargar miniatura: {path_or_url}")
            self.app.after(0, self.create_placeholder_label, "⏱️", font_size=60)
            
        except Exception as e:
            print(f"⚠️ Error al cargar miniatura: {e}")
            self.app.after(0, self.create_placeholder_label, "❌", font_size=60)

    def _classify_format(self, f):
        """
        Clasifica un formato (v3.2 - Manejo de codecs 'unknown')
        """
        ext = f.get('ext', '')
        vcodec = f.get('vcodec', '')
        acodec = f.get('acodec', '')
        format_id = (f.get('format_id') or '').lower()
        format_note = (f.get('format_note') or '').lower()
        protocol = f.get('protocol', '')
        
        # 🆕 REGLA -1: Formato sintético
        if 'audio directo' in format_note or 'livestream' in format_note:
            if 'audio' in format_note:
                return 'AUDIO'
            return 'VIDEO'
        
        # 🆕 REGLA 0: Casos especiales de vcodec literal
        vcodec_special_cases = {
            'audio only': 'AUDIO',
            'images': 'VIDEO',
            'slideshow': 'VIDEO',
        }
        
        if vcodec in vcodec_special_cases:
            return vcodec_special_cases[vcodec]
        
        # 🔧 REGLA 1: GIF explícito
        if ext == 'gif' or vcodec == 'gif':
            return 'VIDEO'
        
        # 🔧 REGLA 2: Tiene dimensiones → VIDEO (con o sin audio)
        if f.get('height') or f.get('width'):
            # 🆕 CRÍTICO: Si ambos codecs son 'unknown' o faltan → ASUMIR COMBINADO
            vcodec_is_unknown = not vcodec or vcodec in ['unknown', 'N/A', '']
            acodec_is_unknown = not acodec or acodec in ['unknown', 'N/A', '']
            
            # Si AMBOS son desconocidos → probablemente es combinado
            if vcodec_is_unknown and acodec_is_unknown:
                print(f"DEBUG: Formato {f.get('format_id')} con codecs desconocidos → asumiendo VIDEO combinado")
                return 'VIDEO'
            
            # Si solo audio es 'none' explícitamente → VIDEO_ONLY
            if acodec in ['none']:
                return 'VIDEO_ONLY'
            
            # Si tiene audio conocido → VIDEO combinado
            return 'VIDEO'
        
        # 🆕 REGLA 2.5: Livestreams
        if f.get('is_live') or 'live' in format_id:
            return 'VIDEO'
        
        # 🔧 REGLA 3: Resolución en format_note
        resolution_patterns = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p', '4320p']
        if any(res in format_note for res in resolution_patterns):
            if acodec in ['none']:
                return 'VIDEO_ONLY'
            return 'VIDEO'
        
        # 🔧 REGLA 4: "audio" explícito en IDs
        if 'audio' in format_id or 'audio' in format_note:
            return 'AUDIO'
        
        # 🆕 REGLA 4.5: "video" explícito en IDs
        if 'video' in format_id or 'video' in format_note:
            # Si tiene dimensiones o codecs desconocidos → asumir combinado
            if f.get('height') or (vcodec == 'unknown' and acodec == 'unknown'):
                return 'VIDEO'
            return 'VIDEO_ONLY' if acodec in ['none'] else 'VIDEO'
        
        # 🔧 REGLA 5: Extensión tiene MÁXIMA PRIORIDAD
        if ext in self.app.AUDIO_EXTENSIONS:
            return 'AUDIO'
        
        # 🆕 REGLA 6: Audio sin video (codec EXPLÍCITAMENTE 'none')
        # IMPORTANTE: 'unknown' NO es lo mismo que 'none'
        if vcodec == 'none' and acodec and acodec not in ['none', '', 'N/A', 'unknown']:
            return 'AUDIO'
        
        # 🆕 REGLA 7: Video sin audio (codec EXPLÍCITAMENTE 'none')
        if acodec == 'none' and vcodec and vcodec not in ['none', '', 'N/A', 'unknown']:
            return 'VIDEO_ONLY'
        
        # 🔧 REGLA 8: Extensión de video + codecs válidos o desconocidos
        if ext in self.app.VIDEO_EXTENSIONS:
            # 🆕 Si ambos codecs son desconocidos → asumir combinado
            if vcodec in ['unknown', ''] and acodec in ['unknown', '']:
                return 'VIDEO'
            return 'VIDEO'
        
        # 🔧 REGLA 9: Ambos codecs explícitamente válidos
        valid_vcodecs = ['h264', 'h265', 'vp8', 'vp9', 'av1', 'hevc', 'mpeg4', 'xvid', 'theora']
        valid_acodecs = ['aac', 'mp3', 'opus', 'vorbis', 'flac', 'ac3', 'eac3', 'pcm']
        
        vcodec_lower = (vcodec or '').lower()
        acodec_lower = (acodec or '').lower()
        
        if vcodec_lower in valid_vcodecs:
            if acodec_lower in valid_acodecs:
                return 'VIDEO'
            else:
                return 'VIDEO_ONLY'
        
        # 🔧 REGLA 10: Protocolo m3u8/dash
        if 'm3u8' in protocol or 'dash' in protocol:
            return 'VIDEO'
        
        # 🆕 REGLA 11: Casos de formatos sin codecs claros pero con metadata
        if f.get('tbr') and not f.get('abr'):
            return 'VIDEO'
        elif f.get('abr') and not f.get('vbr'):
            return 'AUDIO'
        
        # 🆕 REGLA 12: Fallback para casos ambiguos con extensión de video
        if ext in self.app.VIDEO_EXTENSIONS:
            print(f"⚠️ ADVERTENCIA: Formato {f.get('format_id')} ambiguo → asumiendo VIDEO combinado por extensión")
            return 'VIDEO'
        
        # 🔧 REGLA 13: Si llegamos aquí → UNKNOWN
        print(f"⚠️ ADVERTENCIA: Formato sin clasificación clara: {f.get('format_id')} (vcodec={vcodec}, acodec={acodec}, ext={ext})")
        return 'UNKNOWN'
        
    def populate_format_menus(self, info, has_video, has_audio):
        # 🆕 Detectar si es un livestream
        is_live = info.get('is_live', False)
        
        if is_live:
            # Los livestreams no tienen duración conocida
            self.video_duration = 0
            print("DEBUG: 🔴 Contenido en vivo detectado (duración desconocida)")
        
        formats = info.get('formats', [])
        
        # ✅ Validación mejorada
        if not formats:
            error_msg = "Error: No se pudieron extraer formatos de esta URL"
            
            # Mensaje más específico según el caso
            if is_live:
                error_msg = "Error: No se puede analizar este livestream (puede estar offline)"
            elif info.get('extractor_key', '').lower() in ['applepodcasts', 'soundcloud']:
                error_msg = "Error: El extractor no devolvió información de formatos"
            
            print(f"⚠️ ADVERTENCIA: {error_msg}")
            self.progress_label.configure(text=error_msg)
            self._clear_subtitle_menus()
            return

        # 🔧 DEBUG: Ver TODOS los formatos recibidos
        print(f"\nDEBUG: Total de formatos recibidos: {len(formats)}")
        for f in formats:
            format_id = f.get('format_id', 'unknown')
            format_type = self._classify_format(f)
            vcodec = f.get('vcodec', 'N/A')
            acodec = f.get('acodec', 'N/A')
            height = f.get('height', 'N/A')
            protocol = f.get('protocol', 'N/A')
            print(f"  {format_id}: type={format_type}, vcodec={vcodec}, acodec={acodec}, height={height}, protocol={protocol}")
        
        # 🆕 PASADA PREVIA: Detectar si hay ALGUNA fuente de audio disponible
        has_any_audio_source = False
        for f in formats:
            format_type = self._classify_format(f)
            if format_type == 'AUDIO':
                has_any_audio_source = True
                break
            if format_type == 'VIDEO':  # Combinado con audio
                acodec = f.get('acodec')
                if acodec and acodec != 'none':
                    has_any_audio_source = True
                    break
        
        print(f"DEBUG: 🔊 has_any_audio_source = {has_any_audio_source}")
        
        video_entries, audio_entries = [], []
        self.video_formats.clear()
        self.audio_formats.clear()
        
        # 🔧 PASO 1: Pre-análisis MEJORADO para agrupar variantes
        self.combined_variants = {}
        
        for f in formats:
            format_type = self._classify_format(f)
            
            # 🆕 CRÍTICO: Manejar VIDEO, VIDEO_ONLY y AUDIO
            if format_type in ['VIDEO', 'VIDEO_ONLY']:  # 🔧 AGREGADO VIDEO_ONLY
                vcodec_raw = f.get('vcodec')
                acodec_raw = f.get('acodec')
                vcodec = vcodec_raw.split('.')[0] if vcodec_raw else 'none'
                acodec = acodec_raw.split('.')[0] if acodec_raw else 'none'
                is_combined = acodec != 'none' and acodec is not None
                
                if is_combined:
                    fps = f.get('fps')
                    height = f.get('height', 0)
                    fps_val = int(fps) if fps else 0
                    ext = f.get('ext', 'N/A')
                    
                    tbr = f.get('tbr', 0)
                    tbr_rounded = round(tbr / 100) * 100 if tbr else 0
                    
                    quality_key = f"{height}p{fps_val}_{ext}_{vcodec}_{acodec}_tbr{tbr_rounded}"
                    
                    if quality_key not in self.combined_variants:
                        self.combined_variants[quality_key] = []
                    self.combined_variants[quality_key].append(f)
            
        # 🔧 PASO 1.5: Filtrar grupos que NO son realmente multiidioma
        # Un grupo es multiidioma solo si tiene múltiples códigos de idioma DIFERENTES
        real_multilang_keys = set()
        for quality_key, variants in self.combined_variants.items():
            unique_languages = set()
            for variant in variants:
                lang = variant.get('language', '')
                if lang:  # Solo contar si tiene idioma definido
                    unique_languages.add(lang)
            
            # 🔧 CRÍTICO: Solo marcar como multiidioma si hay 2+ idiomas DIFERENTES
            if len(unique_languages) >= 2:
                real_multilang_keys.add(quality_key)
                print(f"DEBUG: Grupo multiidioma detectado: {quality_key} con idiomas {unique_languages}")
        
        # 🔧 PASO 2: Ahora sí crear las entradas con la información correcta
        combined_keys_seen = set()
        
        for f in formats:
            format_type = self._classify_format(f)
            size_mb_str = "Tamaño desc."
            size_sort_priority = 0
            filesize = f.get('filesize') or f.get('filesize_approx')
            if filesize:
                size_mb_str = f"{filesize / (1024*1024):.2f} MB"
                size_sort_priority = 2
            else:
                bitrate = f.get('tbr') or f.get('vbr') or f.get('abr')
                if bitrate and self.video_duration:
                    estimated_bytes = (bitrate*1000/8)*self.video_duration
                    size_mb_str = f"Aprox. {estimated_bytes/(1024*1024):.2f} MB"
                    size_sort_priority = 1
            
            vcodec_raw = f.get('vcodec')
            acodec_raw = f.get('acodec')
            vcodec = vcodec_raw.split('.')[0] if vcodec_raw else 'none'
            acodec = acodec_raw.split('.')[0] if acodec_raw else 'none'
            ext = f.get('ext', 'N/A')
            
            # 🆕 CRÍTICO: Procesar VIDEO y VIDEO_ONLY
            if format_type in ['VIDEO', 'VIDEO_ONLY']:
                is_combined = acodec != 'none' and acodec is not None
                fps = f.get('fps')
                fps_tag = f"{fps:.0f}" if fps else ""
                
                quality_key = None
                if is_combined:
                    height = f.get('height', 0)
                    fps_val = int(fps) if fps else 0
                    tbr = f.get('tbr', 0)
                    tbr_rounded = round(tbr / 100) * 100 if tbr else 0
                    quality_key = f"{height}p{fps_val}_{ext}_{vcodec}_{acodec}_tbr{tbr_rounded}"
                    
                    # 🔧 MODIFICADO: Solo deduplicar si es REALMENTE multiidioma
                    if quality_key in real_multilang_keys:
                        if quality_key in combined_keys_seen:
                            continue
                        combined_keys_seen.add(quality_key)
                
                label_base = f"{f.get('height', 'Video')}p{fps_tag} ({ext}"
                label_codecs = f", {vcodec}+{acodec}" if is_combined else f", {vcodec}"
                
                # 🔧 MODIFICADO: Solo mostrar [Sin Audio] si NO hay audio disponible en el sitio
                no_audio_tag = ""
                if format_type == 'VIDEO_ONLY' and not has_any_audio_source:
                    no_audio_tag = " [Sin Audio]"
                
                # 🔧 MODIFICADO: Solo mostrar "Multiidioma" si está en real_multilang_keys
                audio_lang_tag = ""

                if is_combined and quality_key:
                    if quality_key in real_multilang_keys:
                        audio_lang_tag = f" [Multiidioma]"
                    else:
                        lang_code = f.get('language')
                        if lang_code:
                            norm_code = lang_code.replace('_', '-').lower()
                            lang_name = self.app.LANG_CODE_MAP.get(norm_code, self.app.LANG_CODE_MAP.get(norm_code.split('-')[0], lang_code))
                            audio_lang_tag = f" | Audio: {lang_name}"
                
                label_tag = " [Combinado]" if is_combined else ""
                note = f.get('format_note') or ''
                note_tag = ""  
                informative_keywords = ['hdr', 'premium', 'dv', 'hlg', 'storyboard']
                if any(keyword in note.lower() for keyword in informative_keywords):
                    note_tag = f" [{note}]"
                protocol = f.get('protocol', '')
                protocol_tag = " [Streaming]" if 'm3u8' in protocol else ""
                
                # 🔧 CORREGIDO: Agregar el tag de sin audio
                label = f"{label_base}{label_codecs}){label_tag}{audio_lang_tag}{no_audio_tag}{note_tag}{protocol_tag} - {size_mb_str}"

                tags = []
                compatibility_issues, unknown_issues = self._get_format_compatibility_issues(f)
                if not compatibility_issues and not unknown_issues: 
                    tags.append("✨")
                elif compatibility_issues or unknown_issues:
                    tags.append("⚠️")
                if tags: 
                    label += f" {' '.join(tags)}"

                video_entries.append({
                    'label': label, 
                    'format': f, 
                    'is_combined': is_combined, 
                    'sort_priority': size_sort_priority,
                    'quality_key': quality_key
                })

            # 👇 AQUÍ DEBE IR EL elif - AL MISMO NIVEL QUE EL if DE VIDEO
            elif format_type == 'AUDIO':
                # 🔧 DEBUG: Ver qué información tiene cada audio
                format_id = f.get('format_id', 'unknown')
                lang_code_raw = f.get('language')
                format_note = f.get('format_note', '')
                print(f"DEBUG AUDIO: id={format_id}, language={lang_code_raw}, format_note={format_note}")
                
                abr = f.get('abr') or f.get('tbr')
                lang_code = f.get('language')
                
                lang_name = "Idioma Desconocido"
                if lang_code:
                    norm_code = lang_code.replace('_', '-').lower()
                    lang_name = self.app.LANG_CODE_MAP.get(norm_code, self.app.LANG_CODE_MAP.get(norm_code.split('-')[0], lang_code))
                    print(f"  → norm_code={norm_code}, mapeado a: {lang_name}")
                else:
                    print(f"  → Sin código de idioma")
                
                lang_prefix = f"{lang_name} - " if lang_code else ""
                note = f.get('format_note') or ''
                drc_tag = " (DRC)" if 'DRC' in note else ""
                protocol = f.get('protocol', '')
                protocol_tag = " [Streaming]" if 'm3u8' in protocol else ""
                label = f"{lang_prefix}{abr:.0f}kbps ({acodec}, {ext}){drc_tag}{protocol_tag}" if abr else f"{lang_prefix}Audio ({acodec}, {ext}){drc_tag}{protocol_tag}"
                if acodec in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_acodecs"]: 
                    label += " ✨"
                else: 
                    label += " ⚠️"
                audio_entries.append({'label': label, 'format': f, 'sort_priority': size_sort_priority})
                abr = f.get('abr') or f.get('tbr')
                lang_code = f.get('language')
                
                lang_name = "Idioma Desconocido"
                if lang_code:
                    norm_code = lang_code.replace('_', '-').lower()
                    lang_name = self.app.LANG_CODE_MAP.get(norm_code, self.app.LANG_CODE_MAP.get(norm_code.split('-')[0], lang_code))
                lang_prefix = f"{lang_name} - " if lang_code else ""
                note = f.get('format_note') or ''
                drc_tag = " (DRC)" if 'DRC' in note else ""
                protocol = f.get('protocol', '')
                protocol_tag = " [Streaming]" if 'm3u8' in protocol else ""
                label = f"{lang_prefix}{abr:.0f}kbps ({acodec}, {ext}){drc_tag}{protocol_tag}" if abr else f"{lang_prefix}Audio ({acodec}, {ext}){drc_tag}{protocol_tag}"
                if acodec in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_acodecs"]: 
                    label += " ✨"
                else: 
                    label += " ⚠️"
                audio_entries.append({'label': label, 'format': f, 'sort_priority': size_sort_priority})
        
        video_entries.sort(key=lambda e: (
            -(e['format'].get('height') or 0),      
            1 if "[Combinado]" in e['label'] else 0, 
            0 if "✨" in e['label'] else 1,         
            -(e['format'].get('tbr') or 0)          
        ))
        
        def custom_audio_sort_key(entry):
            f = entry['format']
            lang_code_raw = f.get('language') or ''
            norm_code = lang_code_raw.replace('_', '-')
            lang_priority = self.app.LANGUAGE_ORDER.get(norm_code, self.app.LANGUAGE_ORDER.get(norm_code.split('-')[0], self.app.DEFAULT_PRIORITY))
            quality = f.get('abr') or f.get('tbr') or 0
            return (lang_priority, -quality)
        audio_entries.sort(key=custom_audio_sort_key)
        
        # 🔧 MODIFICADO: Guardar también quality_key en video_formats
        self.video_formats = {
            e['label']: {
                k: e['format'].get(k) for k in ['format_id', 'vcodec', 'acodec', 'ext', 'width', 'height']
            } | {
                'is_combined': e.get('is_combined', False),
                'quality_key': e.get('quality_key')
            } 
            for e in video_entries
        }
        
        self.audio_formats = {e['label']: {k: e['format'].get(k) for k in ['format_id', 'acodec', 'ext']} for e in audio_entries}
        
        # 🔧 AHORA SÍ verificar si hay audio (DESPUÉS de llenar los diccionarios)
        has_any_audio = bool(audio_entries) or any(
            v.get('is_combined', False) for v in self.video_formats.values()
        )
        
        print(f"DEBUG: audio_entries={len(audio_entries)}, has_any_audio={has_any_audio}")
        print(f"DEBUG: video_formats con audio combinado: {sum(1 for v in self.video_formats.values() if v.get('is_combined'))}")
        
        # 🆕 Deshabilitar modo "Solo Audio" si no hay audio
        if not has_any_audio:
            self.mode_selector.set("Video+Audio")
            self.mode_selector.configure(state="disabled", values=["Video+Audio"])
            print("⚠️ ADVERTENCIA: No hay pistas de audio disponibles. Modo Solo Audio deshabilitado.")
        elif not video_entries and audio_entries:
            self.mode_selector.set("Solo Audio")
            self.mode_selector.configure(state="disabled", values=["Solo Audio"])
            print("✅ Solo hay audio. Modo Solo Audio activado.")
        else:
            current_mode = self.mode_selector.get()
            self.mode_selector.configure(state="normal", values=["Video+Audio", "Solo Audio"])
            self.mode_selector.set(current_mode)
            print(f"✅ Ambos modos disponibles. Modo actual: {current_mode}")
        
        self.on_mode_change(self.mode_selector.get())
            
        self.on_mode_change(self.mode_selector.get())
        v_opts = list(self.video_formats.keys()) or ["- Sin Formatos de Video -"]
        a_opts = list(self.audio_formats.keys()) or ["- Sin Pistas de Audio -"]

        default_video_selection = v_opts[0]
        for option in v_opts:
            if "✨" in option:
                default_video_selection = option
                break 
        
        # --- SELECCIÓN INTELIGENTE DE AUDIO ---
        # Regla: Original+Compatible > Original(Cualquiera) > Compatible(Idioma Pref) > Primero
        
        target_audio = None
        
        # Candidatos de reserva
        candidate_original_incompatible = None
        candidate_preferred_compatible = None
        
        for entry in audio_entries:
            f = entry['format']
            label = entry['label']
            note = (f.get('format_note') or '').lower()
            acodec = str(f.get('acodec', '')).split('.')[0]
            
            is_original = 'original' in note
            is_compatible = acodec in self.app.EDITOR_FRIENDLY_CRITERIA["compatible_acodecs"]
            
            # 1. EL GANADOR: Original Y Compatible
            if is_original and is_compatible:
                target_audio = label
                break # Encontrado el mejor caso posible, salimos.
            
            # 2. Reserva A: Original (aunque sea Opus/WebM)
            if is_original and candidate_original_incompatible is None:
                candidate_original_incompatible = label
                
            # 3. Reserva B: Compatible en tu idioma preferido (ej: Español AAC)
            # Como la lista 'audio_entries' YA está ordenada por tu idioma,
            # el primer compatible que encontremos será el mejor de tu idioma.
            if is_compatible and candidate_preferred_compatible is None:
                candidate_preferred_compatible = label

        # Decisión final basada en prioridades
        if target_audio:
            default_audio_selection = target_audio
        elif candidate_original_incompatible:
            # Preferimos el idioma original aunque tengamos que recodificar
            default_audio_selection = candidate_original_incompatible
        elif candidate_preferred_compatible:
            # Si no hay "Original", nos quedamos con el compatible de tu idioma
            default_audio_selection = candidate_preferred_compatible
        else:
            # Fallback total: el primero de la lista
            default_audio_selection = a_opts[0]

        self.video_quality_menu.configure(state="normal" if self.video_formats else "disabled", values=v_opts)
        self.video_quality_menu.set(default_video_selection)
        
        self.audio_quality_menu.configure(state="normal" if self.audio_formats else "disabled", values=a_opts)
        self.audio_quality_menu.set(default_audio_selection)
        self.all_subtitles = {}
        
        def process_sub_list(sub_list, is_auto):
            lang_code_map_3_to_2 = {'spa': 'es', 'eng': 'en', 'jpn': 'ja', 'fra': 'fr', 'deu': 'de', 'por': 'pt', 'ita': 'it', 'kor': 'ko', 'rus': 'ru'}
            for lang_code, subs in sub_list.items():
                primary_part = lang_code.replace('_', '-').split('-')[0].lower()
                grouped_lang_code = lang_code_map_3_to_2.get(primary_part, primary_part)
                for sub_info in subs:
                    sub_info['lang'] = lang_code 
                    sub_info['automatic'] = is_auto
                    self.all_subtitles.setdefault(grouped_lang_code, []).append(sub_info)
        process_sub_list(info.get('subtitles', {}), is_auto=False)
        process_sub_list(info.get('automatic_captions', {}), is_auto=True)
        
        def custom_language_sort_key(lang_code):
            priority = self.app.LANGUAGE_ORDER.get(lang_code, self.app.DEFAULT_PRIORITY)
            return (priority, lang_code)
        available_languages = sorted(self.all_subtitles.keys(), key=custom_language_sort_key)
        if available_languages:
            self.auto_download_subtitle_check.configure(state="normal")
            lang_display_names = [self.app.LANG_CODE_MAP.get(lang, lang) for lang in available_languages]
            self.subtitle_lang_menu.configure(state="normal", values=lang_display_names)
            self.subtitle_lang_menu.set(lang_display_names[0])
            self.on_language_change(lang_display_names[0])
        else:
            self._clear_subtitle_menus()
        self.toggle_manual_subtitle_button()

    def _send_url_to_batch(self, url: str):
        """
        Toma una URL y la envía a la pestaña de Lotes para análisis
        y la cambia a esa pestaña.
        """
        try:
            print(f"INFO: Enviando URL a la pestaña de Lotes: {url}")
            
            # 1. Obtener la pestaña de lotes
            batch_tab = self.app.batch_tab
            if not batch_tab:
                print("ERROR: No se encontró la pestaña de lotes (batch_tab).")
                return
                
            # 2. Poner la URL en la caja de texto de lotes
            batch_tab.url_entry.delete(0, 'end')
            batch_tab.url_entry.insert(0, url)
            
            # 3. Iniciar el análisis en lotes
            # (Usamos 'after' para que la UI se refresque antes de que el análisis empiece)
            self.app.after(10, batch_tab._on_analyze_click)
            
            # 4. Cambiar el foco a la pestaña de lotes
            self.app.tab_view.set("Descarga por Lotes")
            
        except Exception as e:
            print(f"ERROR: No se pudo enviar la URL a Lotes: {e}")

    def manual_poppler_update_check(self):
        """Inicia una comprobación manual de la actualización de Poppler."""
        self.update_poppler_button.configure(state="disabled", text="Buscando...")
        self.poppler_status_label.configure(text="Poppler: Verificando...")
        # Limpiar estado de otros
        self.active_downloads_state["ffmpeg"]["active"] = False
        self.active_downloads_state["deno"]["active"] = False
        self.active_downloads_state["poppler"] = {"text": "", "value": 0.0, "active": False} # Inicializar

        from src.core.setup import check_poppler_status

        def check_task():
            status_info = check_poppler_status(
                lambda text, val: self.update_setup_download_progress('poppler', text, val)
            )
            self.app.after(0, self.app.on_poppler_check_complete, status_info)

        self.active_operation_thread = threading.Thread(target=check_task, daemon=True)
        self.active_operation_thread.start()

    def manual_inkscape_check(self):
        """Verificación manual de Inkscape."""
        self.check_inkscape_button.configure(state="disabled", text="Verificando...")
        self.inkscape_status_label.configure(text="Inkscape: Buscando...")
        
        from src.core.setup import check_inkscape_status

        def check_task():
            # Usamos un callback dummy para el progreso
            status_info = check_inkscape_status(lambda t, v: None)
            self.app.after(0, self.app.on_inkscape_check_complete, status_info)

        threading.Thread(target=check_task, daemon=True).start()

    #-- FUNCIONES PARA DESCOMPONER UN VIDEO EN FRAMES --#

    def _toggle_extract_options(self, *args):
        """Muestra u oculta las opciones de calidad de JPG en el modo Extraer."""
        selected_format = self.extract_format_menu.get()
        if selected_format == "JPG (tamaño reducido)":
            self.extract_jpg_quality_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        else:
            self.extract_jpg_quality_frame.grid_forget()

    def _send_folder_to_image_tools(self):
        """
        Toma la ruta de la carpeta (guardada en self.last_download_path)
        y la envía a la pestaña de Herramientas de Imagen.
        """
        folder_path = self.last_download_path
        if not folder_path or not os.path.isdir(folder_path):
            print(f"ERROR: No se encontró la ruta de la carpeta de fotogramas: {folder_path}")
            return
            
        if not hasattr(self.app, 'image_tab'):
            print("ERROR: No se puede encontrar la pestaña 'image_tab' en la app principal.")
            return

        print(f"INFO: Enviando carpeta '{folder_path}' a Herramientas de Imagen.")
        
        # Llamar a la nueva función pública que creamos en ImageToolsTab
        self.app.image_tab.import_folder_from_path(folder_path)

    def _send_thumbnail_to_image_tools(self):
        """
        Guarda temporalmente la miniatura y la envía a la pestaña de Herramientas de Imagen.
        """
        if not self.pil_image:
            print("ERROR: No hay miniatura disponible para enviar.")
            return
        
        try:
            # 1. Crear carpeta temporal para la miniatura
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="dowp_thumbnail_")
            
            # 2. Guardar la miniatura en esa carpeta
            temp_filename = "miniatura.jpg"
            temp_path = os.path.join(temp_dir, temp_filename)
            
            self.pil_image.convert("RGB").save(temp_path, quality=95)
            print(f"DEBUG: Miniatura guardada temporalmente en: {temp_path}")
            
            # 3. Verificar que existe la pestaña de herramientas de imagen
            if not hasattr(self.app, 'image_tab'):
                print("ERROR: No se puede encontrar la pestaña 'image_tab' en la app principal.")
                messagebox.showerror(
                    "Error",
                    "La pestaña de Herramientas de Imagen no está disponible."
                )
                return
            
            # 4. Enviar la carpeta a la pestaña
            print(f"INFO: Enviando miniatura (carpeta: {temp_dir}) a Herramientas de Imagen.")
            self.app.image_tab.import_folder_from_path(temp_dir)
            
            # 5. Cambiar a la pestaña de herramientas de imagen
            self.app.tab_view.set("Herramientas de Imagen")
            
            print("✅ Miniatura enviada exitosamente a Herramientas de Imagen")
            
        except Exception as e:
            print(f"ERROR: No se pudo enviar la miniatura a Herramientas de Imagen: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror(
                "Error",
                f"No se pudo enviar la miniatura:\n{e}"
            )
    def _execute_extraction_thread(self, options):
        """
        (HILO DE TRABAJO)
        Función dedicada para manejar el "Modo Extraer".
        """
        process_successful = False
        downloaded_filepath = None
        final_output_directory = None
        
        try:
            # --- VALIDACIÓN DE OPCIONES ---
            extract_format = options.get('extract_format', 'png')
            if extract_format not in ['png', 'jpg']:
                raise Exception(f"Formato inválido: {extract_format}")
            
            # Validar calidad JPG si aplica
            if extract_format == 'jpg':
                jpg_quality = options.get('extract_jpg_quality', '2')
                try:
                    quality_int = int(jpg_quality)
                    if not (1 <= quality_int <= 31):
                        self.app.after(0, self.update_progress, -1, 
                                    f"⚠️ Calidad JPG inválida ({jpg_quality}). Usando calidad alta (2).")
                        options['extract_jpg_quality'] = '2'
                except (ValueError, TypeError):
                    options['extract_jpg_quality'] = '2'
            
            # Validar FPS si se especificó
            fps = options.get('extract_fps')
            if fps:
                try:
                    fps_value = float(fps)
                    if fps_value <= 0:
                        raise ValueError("FPS debe ser positivo")
                except (ValueError, TypeError):
                    self.app.after(0, self.update_progress, -1, 
                                f"⚠️ FPS inválido ({fps}). Extrayendo todos los fotogramas.")
                    options['extract_fps'] = None

            # --- 1. MODO LOCAL ---
            if self.local_file_path:
                print("DEBUG: [Modo Extraer] Iniciando desde archivo local.")
                filepath_to_process = self.local_file_path
                
                # Definir la carpeta de salida
                output_dir = self.output_path_entry.get()
                if self.save_in_same_folder_check.get() == 1:
                    output_dir = os.path.dirname(filepath_to_process)
                
                # 🆕 Usar nombre personalizado si se especificó
                custom_folder_name = self.extract_folder_name_entry.get().strip()
                if custom_folder_name:
                    folder_name = self.sanitize_filename(custom_folder_name)
                else:
                    base_filename = self.sanitize_filename(options['title'])
                    folder_name = f"{base_filename}_frames"
                
                final_output_directory = os.path.join(output_dir, folder_name)

            # --- 2. MODO URL ---
            else:
                print("DEBUG: [Modo Extraer] Iniciando desde URL.")
                output_dir = options["output_path"]
                
                # 🆕 Determinar el nombre base PRIMERO
                base_filename = self.sanitize_filename(options['title'])
                
                # 🆕 Usar nombre personalizado si se especificó
                custom_folder_name = self.extract_folder_name_entry.get().strip()
                if custom_folder_name:
                    folder_name = self.sanitize_filename(custom_folder_name)
                else:
                    folder_name = f"{base_filename}_frames"
                
                # Creamos un nombre de archivo falso para el chequeo de conflicto
                temp_check_path = os.path.join(output_dir, f"{folder_name}.check")
                
                final_download_path, backup_file_path = self._resolve_output_path(temp_check_path)
                
                # El nombre de nuestra carpeta se basa en el nombre resuelto
                final_folder_name = os.path.splitext(os.path.basename(final_download_path))[0]
                final_output_directory = os.path.join(output_dir, final_folder_name)
                
                # Descargar el video (lógica de _perform_download)
                downloaded_filepath, temp_video_for_extraction = self._perform_download(
                    options, 
                    f"{base_filename}_temp_video",  # ✅ Ahora base_filename está definido
                    audio_extraction_fallback=False
                )
                
                filepath_to_process = downloaded_filepath

            # --- 3. EJECUTAR EXTRACCIÓN ---
            if self.cancellation_event.is_set():
                raise UserCancelledError("Proceso cancelado por el usuario.")
            
            self.app.after(0, self.update_progress, -1, "Iniciando extracción de fotogramas...")
            
            # Preparar opciones para el procesador
            extraction_options = {
                'input_file': filepath_to_process,
                'output_folder': final_output_directory,
                'image_format': options.get('extract_format'),
                'fps': options.get('extract_fps'),
                'jpg_quality': options.get('extract_jpg_quality'),
                'duration': self.video_duration, # Usar la duración completa
                'pre_params': [] # No se usa recorte aquí (aún)
            }
            
            # Llamar a la nueva función del procesador
            output_folder = self.ffmpeg_processor.execute_video_to_images(
                extraction_options,
                lambda p, m: self.update_progress(p, f"Extrayendo... {p:.1f}%"),
                self.cancellation_event
            )
            
            process_successful = True
            
            # El "archivo final" es ahora una CARPETA
            self.app.after(0, self.on_process_finished, True, "Extracción completada.", output_folder)

        except UserCancelledError as e:
            self.app.after(0, self.on_process_finished, False, str(e), None)
        except Exception as e:
            cleaned_message = self._clean_ansi_codes(str(e))
            self.app.after(0, self.on_process_finished, False, cleaned_message, None)
            
        finally:
            # 🆕 Limpiar el video temporal si se descargó (respetando el checkbox)
            if downloaded_filepath and os.path.exists(downloaded_filepath):
                # Solo eliminar si NO es modo local Y el usuario NO quiere conservar el original
                should_delete = not self.local_file_path and not self.keep_original_extract_checkbox.get()
                
                if should_delete:
                    try:
                        os.remove(downloaded_filepath)
                        print(f"DEBUG: Archivo de video temporal eliminado: {downloaded_filepath}")
                    except OSError as e:
                        print(f"ADVERTENCIA: No se pudo eliminar el video temporal: {e}")
                else:
                    # ✅ Si se conserva, renombrar para quitar el "_temp_video"
                    try:
                        # Calcular el nuevo nombre sin el sufijo temporal
                        dir_path = os.path.dirname(downloaded_filepath)
                        old_basename = os.path.basename(downloaded_filepath)
                        
                        # Remover "_temp_video" del nombre
                        if "_temp_video" in old_basename:
                            new_basename = old_basename.replace("_temp_video", "")
                            new_filepath = os.path.join(dir_path, new_basename)
                            
                            # Verificar si ya existe un archivo con ese nombre
                            if os.path.exists(new_filepath):
                                print(f"DEBUG: Ya existe un archivo con el nombre final, conservando con '_temp_video': {downloaded_filepath}")
                            else:
                                os.rename(downloaded_filepath, new_filepath)
                                print(f"DEBUG: Video renombrado de '{old_basename}' a '{new_basename}'")
                                downloaded_filepath = new_filepath  # Actualizar la referencia
                        
                        print(f"DEBUG: Video original conservado en: {downloaded_filepath}")
                        
                    except Exception as e:
                        print(f"ADVERTENCIA: No se pudo renombrar el video conservado: {e}")
                        print(f"DEBUG: Video conservado con nombre temporal: {downloaded_filepath}")

    # ============================================
    # DRAG & DROP FUNCTIONALITY
    # ============================================

    def _on_drag_enter(self, event):
        """Efecto visual cuando el archivo entra al área de drop"""
        print("DEBUG: 🎯 _on_drag_enter ejecutado")
        
        self.thumbnail_container.configure(border_width=4, border_color="#007BFF")
        self.dnd_overlay.configure(bg="#1a3d5c")
        
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label and self.thumbnail_label.winfo_exists():
            self.thumbnail_label.place_forget()
        
        if hasattr(self, '_drag_label') and self._drag_label and self._drag_label.winfo_exists():
            self._drag_label.destroy()
        
        self._drag_label = ctk.CTkLabel(
            self.dnd_overlay,
            text="📂 Suelta tu archivo aquí\n\n(Video o Audio)",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#00BFFF"
        )
        self._drag_label.place(relx=0.5, rely=0.5, anchor="center")
        self.dnd_overlay.lift()

    def _on_drag_leave(self, event):
        """Restaurar estilo normal cuando el archivo sale del área"""
        print("DEBUG: 🔙 _on_drag_leave ejecutado")
        
        self.thumbnail_container.configure(border_width=0)
        
        try:
            original_bg = self._get_ctk_fg_color(self.thumbnail_container)
            self.dnd_overlay.configure(bg=original_bg)
        except:
            self.dnd_overlay.configure(bg="#2B2B2B")
        
        if hasattr(self, '_drag_label') and self._drag_label and self._drag_label.winfo_exists():
            self._drag_label.destroy()
            self._drag_label = None
        
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label and self.thumbnail_label.winfo_exists():
            if self.pil_image:
                self.thumbnail_label.pack(expand=True)
            else:
                self.thumbnail_label.pack(expand=True, fill="both")

    def _on_file_drop(self, event):
        """Maneja archivos arrastrados"""
        try:
            self._show_drop_feedback()
            
            files = self.tk.splitlist(event.data)
            
            if not files:
                print("DEBUG: No se detectaron archivos en el drop")
                self._hide_drop_feedback()
                return
            
            file_path = files[0].strip('{}')
            print(f"DEBUG: 📁 Archivo arrastrado: {file_path}")
            
            if not os.path.isfile(file_path):
                print("ADVERTENCIA: Solo se aceptan archivos, no carpetas")
                self.progress_label.configure(text="Solo se aceptan archivos")  # ✅ Más simple
                self._hide_drop_feedback()
                return
            
            valid_extensions = VIDEO_EXTENSIONS.union(AUDIO_EXTENSIONS)
            file_ext = os.path.splitext(file_path)[1].lower().lstrip('.')
            
            if file_ext not in valid_extensions:
                print(f"ADVERTENCIA: Formato no soportado: {file_ext}")
                self.progress_label.configure(text=f"Formato '.{file_ext}' no soportado")  # ✅ Sin emoji
                self._hide_drop_feedback()
                return
            
            self._hide_drop_feedback()
            self._import_file_from_path(file_path)
            
        except Exception as e:
            print(f"ERROR en drag & drop: {e}")
            import traceback
            traceback.print_exc()
            self._hide_drop_feedback()

    def _import_file_from_path(self, file_path):
        """
        Importa un archivo local desde una ruta conocida (usado por drag & drop).
        Similar a import_local_file pero sin diálogo.
        """
        self.reset_to_url_mode()
        self.auto_save_thumbnail_check.pack_forget()
        self.cancellation_event.clear()
        self.progress_label.configure(text=f"Analizando archivo: {os.path.basename(file_path)}...")
        self.progress_bar.start()
        self.open_folder_button.configure(state="disabled")
        
        threading.Thread(target=self._process_local_file_info, args=(file_path,), daemon=True).start()

    def enable_drag_and_drop(self):
        """
        Habilita drag & drop en el overlay nativo de Tkinter.
        """
        try:
            from tkinterdnd2 import DND_FILES
            
            if not hasattr(self, 'dnd_overlay'):
                print("ERROR: dnd_overlay no fue creado. Verifica _create_widgets()")
                return
            
            try:
                version = self.app.tk.call('package', 'present', 'tkdnd')
                print(f"DEBUG: TkinterDnD versión {version} detectada")
            except Exception as e:
                print(f"ERROR CRÍTICO: TkinterDnD no está cargado: {e}")
                return
            
            # ✅ Registrar solo el evento de Drop (el que SÍ funciona en Windows)
            self.dnd_overlay.drop_target_register(DND_FILES)
            self.dnd_overlay.dnd_bind('<<Drop>>', self._on_file_drop)
            
            # ✅ NUEVO: Usar eventos de mouse nativos para el feedback visual
            self.dnd_overlay.bind('<Enter>', self._on_mouse_enter)
            self.dnd_overlay.bind('<Leave>', self._on_mouse_leave)
            
            self.dnd_overlay.lift()
            
            print("DEBUG: ✅ Drag & Drop habilitado en el área de miniatura")
            
        except ImportError:
            print("ADVERTENCIA: tkinterdnd2 no está instalado. Drag & Drop no disponible.")
        except Exception as e:
            print(f"ERROR habilitando Drag & Drop: {e}")
            import traceback
            traceback.print_exc()

    def _on_mouse_enter(self, event):
        """Se ejecuta cuando el mouse entra en el área de drop"""
        
        # ✅ Verificar que el thumbnail_label existe y es válido
        if not hasattr(self, 'thumbnail_label') or not self.thumbnail_label:
            return
        
        try:
            if not self.thumbnail_label.winfo_exists():
                return
        except:
            return
        
        # ✅ No hacer nada si está analizando
        try:
            current_text = self.thumbnail_label.cget("text")
            if "Analizando" in current_text or "Cargando" in current_text:
                return
        except:
            return
        
        # CASO 1: Sin archivo cargado (placeholder vacío)
        if not self.pil_image and not self.local_file_path:
            try:
                self.thumbnail_label.configure(
                    text="Arrastra un archivo aquí (Video o Audio) \n Para activar el modo de Recodificación Local",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    fg_color="#1a1a1a"
                )
            except:
                pass
        
        # CASO 2: Ya hay algo cargado (miniatura o archivo local)
        # ✅ MODIFICADO: Verificar PRIMERO si hay imagen, sin importar si es local o URL
        elif self.pil_image:
            try:
                # ✅ Guardar la imagen original solo si no está guardada
                if not hasattr(self, '_original_image_backup') or self._original_image_backup is None:
                    self._original_image_backup = self.pil_image.copy()
                    print(f"DEBUG: Imagen guardada para oscurecer (local={bool(self.local_file_path)})")
                
                # ✅ Oscurecer la imagen
                if hasattr(self, '_original_image_backup') and self._original_image_backup:
                    from PIL import ImageEnhance
                    enhancer = ImageEnhance.Brightness(self._original_image_backup)
                    darkened_image = enhancer.enhance(0.4)
                    
                    display_image = darkened_image.copy()
                    display_image.thumbnail((320, 180), Image.Resampling.LANCZOS)
                    ctk_image = ctk.CTkImage(light_image=display_image, dark_image=display_image, size=display_image.size)
                    
                    self.thumbnail_label.configure(image=ctk_image, text="")
                    self.thumbnail_label.image = ctk_image
                    print("DEBUG: Imagen oscurecida correctamente")
                
                # ✅ Mostrar texto encima
                if not hasattr(self, '_hover_text_label') or self._hover_text_label is None:
                    self._hover_text_label = ctk.CTkLabel(
                        self.dnd_overlay,
                        text="Arrastra un archivo aquí (Video o Audio) \n Para activar el modo de Recodificación Local",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color="#FFFFFF",
                        fg_color="transparent",
                        bg_color="transparent"
                    )
                    self._hover_text_label.place(relx=0.5, rely=0.5, anchor="center")
                elif self._hover_text_label:
                    try:
                        if not self._hover_text_label.winfo_ismapped():
                            self._hover_text_label.place(relx=0.5, rely=0.5, anchor="center")
                    except:
                        self._hover_text_label = ctk.CTkLabel(
                            self.dnd_overlay,
                            text="Arrastra un archivo aquí (Video o Audio) \n Para activar el modo de Recodificación Local",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color="#FFFFFF",
                            fg_color="transparent",
                            bg_color="transparent"
                        )
                        self._hover_text_label.place(relx=0.5, rely=0.5, anchor="center")
            except Exception as e:
                print(f"DEBUG: Error oscureciendo imagen: {e}")
                import traceback
                traceback.print_exc()
        
        # CASO 3: Archivo local SIN miniatura (solo emoji 🎵)
        elif self.local_file_path and not self.pil_image:
            try:
                self.thumbnail_label.configure(fg_color="#1a1a1a")
                
                # Mostrar texto encima
                if not hasattr(self, '_hover_text_label') or self._hover_text_label is None:
                    self._hover_text_label = ctk.CTkLabel(
                        self.dnd_overlay,
                        text="Arrastra un archivo aquí (Video o Audio) \n Para activar el modo de Recodificación Local",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color="#FFFFFF",
                        fg_color="transparent",
                        bg_color="transparent"
                    )
                    self._hover_text_label.place(relx=0.5, rely=0.5, anchor="center")
            except Exception as e:
                print(f"DEBUG: Error en caso local sin imagen: {e}")

    def _on_mouse_leave(self, event):
        """Se ejecuta cuando el mouse sale del área de drop"""
        
        # ✅ Verificar que el thumbnail_label existe
        if not hasattr(self, 'thumbnail_label') or not self.thumbnail_label:
            return
        
        try:
            if not self.thumbnail_label.winfo_exists():
                return
        except:
            return
        
        # ✅ No hacer nada si está analizando
        try:
            current_text = self.thumbnail_label.cget("text")
            if "Analizando" in current_text or "Cargando" in current_text:
                return
        except:
            return
        
        # CASO 1: Sin archivo cargado (restaurar fondo y texto normal)
        if not self.pil_image and not self.local_file_path:
            try:
                original_bg = self._get_ctk_fg_color(self.thumbnail_container)
                self.thumbnail_label.configure(
                    text="Miniatura",
                    font=ctk.CTkFont(size=14),
                    fg_color=original_bg
                )
            except:
                try:
                    self.thumbnail_label.configure(
                        text="Miniatura",
                        font=ctk.CTkFont(size=14),
                        fg_color="#2B2B2B"
                    )
                except:
                    pass
        
        # CASO 2: Hay imagen (URL o local)
        elif self.pil_image:
            try:
                # ✅ Restaurar la imagen original
                if hasattr(self, '_original_image_backup') and self._original_image_backup:
                    display_image = self._original_image_backup.copy()
                    display_image.thumbnail((320, 180), Image.Resampling.LANCZOS)
                    ctk_image = ctk.CTkImage(light_image=display_image, dark_image=display_image, size=display_image.size)
                    
                    self.thumbnail_label.configure(image=ctk_image, text="")
                    self.thumbnail_label.image = ctk_image
                    print("DEBUG: Imagen restaurada correctamente")
                
                # ✅ Destruir el texto de hover
                if hasattr(self, '_hover_text_label') and self._hover_text_label is not None:
                    try:
                        if self._hover_text_label.winfo_exists():
                            self._hover_text_label.destroy()
                    except:
                        pass
                    self._hover_text_label = None
            except Exception as e:
                print(f"DEBUG: Error restaurando imagen: {e}")
                import traceback
                traceback.print_exc()
        
        # CASO 3: Archivo local sin imagen
        elif self.local_file_path and not self.pil_image:
            try:
                original_bg = self._get_ctk_fg_color(self.thumbnail_container)
                self.thumbnail_label.configure(fg_color=original_bg)
                
                # Destruir texto
                if hasattr(self, '_hover_text_label') and self._hover_text_label is not None:
                    try:
                        if self._hover_text_label.winfo_exists():
                            self._hover_text_label.destroy()
                    except:
                        pass
                    self._hover_text_label = None
            except Exception as e:
                print(f"DEBUG: Error en caso local sin imagen (leave): {e}")

    def _show_drop_feedback(self):
        """Muestra feedback visual cuando se detecta un drop"""
        try:
            # Cambiar borde
            self.thumbnail_container.configure(border_width=2, border_color="#007BFF")
            
            # ✅ NO tocar el overlay, solo el thumbnail_label
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label:
                try:
                    if self.thumbnail_label.winfo_exists():
                        self.thumbnail_label.place_forget()
                except:
                    pass
            
            # Crear label de feedback
            if hasattr(self, '_drop_feedback_label') and self._drop_feedback_label:
                try:
                    if self._drop_feedback_label.winfo_exists():
                        self._drop_feedback_label.destroy()
                except:
                    pass
            
            self._drop_feedback_label = ctk.CTkLabel(
                self.dnd_overlay,
                text="Procesando archivo...",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="transparent",
                bg_color="transparent"
            )
            self._drop_feedback_label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception as e:
            print(f"DEBUG: Error en _show_drop_feedback: {e}")

    def _hide_drop_feedback(self):
        """Oculta el feedback visual del drop"""
        try:
            # Restaurar borde
            self.thumbnail_container.configure(border_width=0)
            
            # Destruir label de feedback
            if hasattr(self, '_drop_feedback_label') and self._drop_feedback_label:
                try:
                    if self._drop_feedback_label.winfo_exists():
                        self._drop_feedback_label.destroy()
                except:
                    pass
                self._drop_feedback_label = None
            
            # Restaurar thumbnail
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label:
                try:
                    if self.thumbnail_label.winfo_exists():
                        if self.pil_image:
                            self.thumbnail_label.pack(expand=True)
                        else:
                            self.thumbnail_label.pack(expand=True, fill="both")
                except:
                    pass
        except Exception as e:
            print(f"DEBUG: Error en _hide_drop_feedback: {e}")

    def manual_ghostscript_check(self):
        """Verificación manual de Ghostscript."""
        self.check_ghostscript_button.configure(state="disabled", text="Verificando...")
        self.ghostscript_status_label.configure(text="Ghostscript: Buscando...")
        
        from src.core.setup import check_ghostscript_status

        def check_task():
            # Callback dummy para el progreso
            status_info = check_ghostscript_status(lambda t, v: None)
            self.app.after(0, self.app.on_ghostscript_check_complete, status_info)

        threading.Thread(target=check_task, daemon=True).start()

    def _open_ai_models_folder(self):
        """Abre la carpeta donde se guardan los modelos de IA."""
        if not os.path.exists(MODELS_DIR):
            try:
                os.makedirs(MODELS_DIR, exist_ok=True)
            except:
                pass

        print(f"INFO: Abriendo carpeta de modelos: {MODELS_DIR}")
        try:
            if os.name == 'nt': # Windows
                os.startfile(MODELS_DIR)
            elif sys.platform == 'darwin': # Mac
                subprocess.Popen(['open', MODELS_DIR])
            else: # Linux
                subprocess.Popen(['xdg-open', MODELS_DIR])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")
