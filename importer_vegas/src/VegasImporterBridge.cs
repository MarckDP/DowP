using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using ScriptPortal.Vegas;

namespace DowPImporter
{
    public class VegasImporterBridge
    {
        private readonly Vegas myVegas;
        private readonly DowPDockableControl myControl;
        private readonly System.Windows.Forms.Control invokeControl;
        private readonly SynchronizationContext mainContext;
        private HttpListener httpListener;
        private Thread listenerThread;
        private bool isRunning;
        private readonly JavaScriptSerializer jsonSerializer = new JavaScriptSerializer();
        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(2.5) };

        public const int VegasPort = 18946;
        public const int DowPPort = 7788;

        public VegasImporterBridge(Vegas vegas, DowPDockableControl control)
        {
            myVegas = vegas;
            myControl = control;
            
            // This control belongs to VEGAS' UI thread once LoadDockView returns.
            // Do not create an unparented WinForms handle: it has no reliable
            // message loop in older VEGAS versions.
            invokeControl = myControl;
            mainContext = SynchronizationContext.Current;

            myControl.SendToDowPRequested += (s, e) => SendSelectionToDowP();
            myControl.ToggleLinkRequested += (s, e) => ToggleLinkDowP();
        }

        public void Start()
        {
            DowPImporterModule.Log("VegasImporterBridge.Start called");
            for (int attempt = 1; attempt <= 3; attempt++)
            {
                try
                {
                    httpListener = new HttpListener();
                    httpListener.Prefixes.Add($"http://127.0.0.1:{VegasPort}/");
                    httpListener.Start();
                    isRunning = true;
                    DowPImporterModule.Log($"HttpListener successfully started on port {VegasPort} (attempt {attempt})");
                    break;
                }
                catch (Exception ex)
                {
                    DowPImporterModule.Log($"HttpListener start attempt {attempt} failed: {ex.Message}");
                    try { httpListener?.Close(); } catch { }
                    httpListener = null;
                    if (attempt < 3)
                    {
                        Thread.Sleep(500);
                    }
                }
            }

            if (!isRunning)
            {
                DowPImporterModule.Log("Failed to start HttpListener on port " + VegasPort);
                myControl.SetLog("No se pudo iniciar el listener local en puerto " + VegasPort);
                return;
            }

            listenerThread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "DowPVegasListener"
            };
            listenerThread.Start();
        }

        public void Stop()
        {
            isRunning = false;
            try
            {
                httpListener?.Stop();
                httpListener?.Close();
            }
            catch { }
        }

        private void ListenLoop()
        {
            while (isRunning && httpListener.IsListening)
            {
                try
                {
                    HttpListenerContext context = httpListener.GetContext();
                    ThreadPool.QueueUserWorkItem(ProcessRequest, context);
                }
                catch (HttpListenerException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    myControl.SetLog("Error en listener: " + ex.Message);
                }
            }
        }

        private void ProcessRequest(object state)
        {
            HttpListenerContext context = (HttpListenerContext)state;
            HttpListenerRequest req = context.Request;
            HttpListenerResponse res = context.Response;

            // Soporte CORS para llamadas locales
            res.Headers.Add("Access-Control-Allow-Origin", "*");
            res.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            res.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

            if (req.HttpMethod == "OPTIONS")
            {
                res.StatusCode = 200;
                res.Close();
                return;
            }

            try
            {
                string rawUrl = req.Url.AbsolutePath.ToLowerInvariant();
                string method = req.HttpMethod;

                if (method == "GET" && rawUrl == "/status")
                {
                    var statusObj = new
                    {
                        status = "ok",
                        app = "vegas",
                        hasProject = true, // Removido myVegas.Project != null para evitar crash en thread secundario
                        isLinked = myControl.IsLinked,
                        isConnected = myControl.IsConnected
                    };
                    WriteJsonResponse(res, statusObj, 200);
                    return;
                }

                if (method == "POST" && rawUrl == "/set_linked")
                {
                    string body = ReadRequestBody(req);
                    var payload = jsonSerializer.Deserialize<Dictionary<string, object>>(body);
                    bool linked = false;
                    if (payload != null && payload.ContainsKey("linked"))
                    {
                        linked = Convert.ToBoolean(payload["linked"]);
                    }
                    myControl.SetLinkedState(true, linked, linked ? "Vinculado con DowP." : "Desvinculado.");
                    WriteJsonResponse(res, new { success = true, isLinked = linked }, 200);
                    return;
                }

                if (method == "POST" && rawUrl == "/import")
                {
                    string body = ReadRequestBody(req);
                    var payload = jsonSerializer.Deserialize<Dictionary<string, object>>(body);

                    bool addToTimeline = myControl.AddToTimeline;
                    if (payload != null && payload.ContainsKey("addToTimeline"))
                    {
                        addToTimeline = Convert.ToBoolean(payload["addToTimeline"]);
                    }

                    bool importImages = myControl.ImportImages;
                    if (payload != null && payload.ContainsKey("importImages"))
                    {
                        importImages = Convert.ToBoolean(payload["importImages"]);
                    }

                    List<string> files = new List<string>();
                    if (payload != null && payload.ContainsKey("files") && payload["files"] is ArrayList fileList)
                    {
                        foreach (var f in fileList)
                        {
                            if (f != null && File.Exists(f.ToString()))
                            {
                                files.Add(f.ToString());
                            }
                        }
                    }

                    int count = 0;
                    if (mainContext != null)
                    {
                        mainContext.Send(state =>
                        {
                            count = ExecuteImport(files, addToTimeline, importImages);
                        }, null);
                    }
                    else if (invokeControl.IsHandleCreated)
                    {
                        invokeControl.Invoke(new Action(() =>
                        {
                            count = ExecuteImport(files, addToTimeline, importImages);
                        }));
                    }
                    else
                    {
                        DowPImporterModule.Log("ERROR: mainContext is null and invokeControl handle not created.");
                    }

                    myControl.SetLog($"✅ {count} archivo(s) importado(s).");
                    WriteJsonResponse(res, new { success = true, importedCount = count }, 200);
                    return;
                }

                if (method == "POST" && rawUrl == "/import_subclips")
                {
                    string body = ReadRequestBody(req);
                    var payload = jsonSerializer.Deserialize<Dictionary<string, object>>(body);

                    int count = 0;
                    if (mainContext != null)
                    {
                        mainContext.Send(state =>
                        {
                            count = ExecuteImportSubclips(payload);
                        }, null);
                    }
                    else if (invokeControl.IsHandleCreated)
                    {
                        invokeControl.Invoke(new Action(() =>
                        {
                            count = ExecuteImportSubclips(payload);
                        }));
                    }
                    else
                    {
                        DowPImporterModule.Log("ERROR: mainContext is null and invokeControl handle not created. Cannot import subclips.");
                    }

                    myControl.SetLog($"✅ {count} subclip(s) importado(s).");
                    WriteJsonResponse(res, new { success = true, subclipsCount = count }, 200);
                    return;
                }

                res.StatusCode = 404;
                WriteJsonResponse(res, new { error = "Not found" }, 404);
            }
            catch (Exception ex)
            {
                res.StatusCode = 500;
                WriteJsonResponse(res, new { error = ex.Message }, 500);
            }
        }

        private int ExecuteImport(List<string> files, bool addToTimeline, bool importImages)
        {
            if (myVegas.Project == null || files.Count == 0) return 0;

            int imported = 0;
            using (UndoBlock undo = new UndoBlock("Importar medios desde DowP"))
            {
                foreach (string filePath in files)
                {
                    try
                    {
                        string normalizedPath = filePath.Replace('/', '\\');
                        DowPImporterModule.Log($"Adding media to pool: {normalizedPath}");
                        Media media = myVegas.Project.MediaPool.AddMedia(normalizedPath);
                        DowPImporterModule.Log($"Media added. HasVideo: {media.HasVideo()}, HasAudio: {media.HasAudio()}");

                        if (!media.HasVideo() && !media.HasAudio())
                        {
                            DowPImporterModule.Log($"Media streams failed to load (incompatible format). Removing to prevent crash.");
                            myVegas.Project.MediaPool.Remove(media);
                            throw new Exception("El decodificador de VEGAS no reconoce el formato de este archivo.");
                        }

                        if (addToTimeline)
                        {
                            bool isImage = IsImageFile(filePath);
                            if (isImage && !importImages)
                            {
                                imported++;
                                continue;
                            }

                            DowPImporterModule.Log($"Inserting media to timeline...");
                            InsertMediaToTimeline(media);
                            DowPImporterModule.Log($"Media inserted to timeline.");
                        }

                        imported++;
                        DowPImporterModule.Log($"Finished importing: {filePath}");
                    }
                    catch (Exception ex)
                    {
                        DowPImporterModule.Log($"Exception in ExecuteImport loop: {ex.Message}\n{ex.StackTrace}");
                        myControl.SetLog($"Error importando {Path.GetFileName(filePath)}: {ex.Message}");
                    }
                }
            }
            return imported;
        }

        private void InsertMediaToTimeline(Media media)
        {
            DowPImporterModule.Log($"InsertMediaToTimeline started.");
            Timecode cursor = myVegas.Transport.CursorPosition;
            Timecode length = media.Length;

            // Por seguridad con imágenes estáticas que reporten longitud <= 0
            if (length.ToMilliseconds() <= 0)
            {
                length = Timecode.FromSeconds(5.0);
            }

            DowPImporterModule.Log($"Cursor: {cursor.ToString()}, Length: {length.ToString()}");

            VideoEvent vEvent = null;
            AudioEvent aEvent = null;

            try {
                // Video / Imagen
                if (media.HasVideo())
                {
                    DowPImporterModule.Log($"Creating/getting video track...");
                    VideoTrack vTrack = GetOrCreateVideoTrack(cursor, length);
                    DowPImporterModule.Log($"Adding video event...");
                    vEvent = vTrack.AddVideoEvent(cursor, length);
                    DowPImporterModule.Log($"Getting video stream...");
                    VideoStream vStream = media.GetVideoStreamByIndex(0);
                    DowPImporterModule.Log($"Adding take to video event...");
                    vEvent.AddTake(vStream);
                    DowPImporterModule.Log($"Take added.");
                }

                // Audio
                if (media.HasAudio())
                {
                    DowPImporterModule.Log($"Creating/getting audio track...");
                    AudioTrack aTrack = GetOrCreateAudioTrack(cursor, length);
                    DowPImporterModule.Log($"Adding audio event...");
                    aEvent = aTrack.AddAudioEvent(cursor, length);
                    DowPImporterModule.Log($"Getting audio stream...");
                    AudioStream aStream = media.GetAudioStreamByIndex(0);
                    DowPImporterModule.Log($"Adding take to audio event...");
                    aEvent.AddTake(aStream);
                    DowPImporterModule.Log($"Take added.");
                }

                // Agrupar evento de video y audio si ambos existen
                if (vEvent != null && aEvent != null)
                {
                    DowPImporterModule.Log($"Grouping events...");
                    TrackEventGroup group = new TrackEventGroup();
                    myVegas.Project.Groups.Add(group);
                    group.Add(vEvent);
                    group.Add(aEvent);
                    DowPImporterModule.Log($"Events grouped.");
                }

                // Avanzar el cursor de reproducción al final del evento importado
                DowPImporterModule.Log($"Updating cursor position...");
                myVegas.UpdateUI();
                myVegas.Transport.CursorPosition = cursor + length;
                DowPImporterModule.Log($"InsertMediaToTimeline finished.");
            } catch (Exception ex) {
                DowPImporterModule.Log($"Exception in InsertMediaToTimeline: {ex.Message}\n{ex.StackTrace}");
                throw;
            }
        }

        private int ExecuteImportSubclips(Dictionary<string, object> payload)
        {
            if (myVegas.Project == null) return 0;
            string filePath = payload.ContainsKey("filePath") ? payload["filePath"]?.ToString() : null;
            if (string.IsNullOrEmpty(filePath) || !File.Exists(filePath)) return 0;

            if (!payload.ContainsKey("subclips") || !(payload["subclips"] is ArrayList subclipsList)) return 0;

            int imported = 0;
            using (UndoBlock undo = new UndoBlock("Importar subclips desde DowP"))
            {
                string normalizedPath = filePath.Replace('/', '\\');
                DowPImporterModule.Log($"Adding media to pool for subclips: {normalizedPath}");
                Media media = myVegas.Project.MediaPool.AddMedia(normalizedPath);
                DowPImporterModule.Log($"Media added. HasVideo: {media.HasVideo()}, HasAudio: {media.HasAudio()}");

                if (!media.HasVideo() && !media.HasAudio())
                {
                    DowPImporterModule.Log($"Media streams failed to load (incompatible format). Removing to prevent crash.");
                    myVegas.Project.MediaPool.Remove(media);
                    throw new Exception("El decodificador de VEGAS no reconoce el formato de este archivo.");
                }

                foreach (var scObj in subclipsList)
                {
                    if (!(scObj is Dictionary<string, object> sc)) continue;

                    string name = sc.ContainsKey("name") ? sc["name"]?.ToString() : Path.GetFileName(filePath);
                    double inSec = sc.ContainsKey("in") ? Convert.ToDouble(sc["in"]) : 0.0;
                    double outSec = sc.ContainsKey("out") ? Convert.ToDouble(sc["out"]) : 0.0;
                    double durationSec = outSec - inSec;

                    if (durationSec <= 0) continue;

                    DowPImporterModule.Log($"Creating subclip {name}");
                    Subclip subclip = new Subclip(myVegas.Project, normalizedPath, Timecode.FromSeconds(inSec), Timecode.FromSeconds(durationSec), false, name);

                    if (myControl.AddToTimeline)
                    {
                        Timecode cursor = myVegas.Transport.CursorPosition;
                        Timecode length = Timecode.FromSeconds(durationSec);

                        VideoEvent vEvent = null;
                        AudioEvent aEvent = null;

                        try {
                            if (media.HasVideo())
                            {
                                DowPImporterModule.Log($"Creating/getting video track (subclip)...");
                                VideoTrack vTrack = GetOrCreateVideoTrack(cursor, length);
                                DowPImporterModule.Log($"Adding video event (subclip)...");
                                vEvent = vTrack.AddVideoEvent(cursor, length);
                                DowPImporterModule.Log($"Getting video stream (subclip)...");
                                VideoStream vStream = media.GetVideoStreamByIndex(0);
                                DowPImporterModule.Log($"Adding take to video event (subclip)...");
                                Take take = vEvent.AddTake(vStream);
                                take.Offset = Timecode.FromSeconds(inSec);
                                DowPImporterModule.Log($"Take added.");
                            }

                            if (media.HasAudio())
                            {
                                DowPImporterModule.Log($"Creating/getting audio track (subclip)...");
                                AudioTrack aTrack = GetOrCreateAudioTrack(cursor, length);
                                DowPImporterModule.Log($"Adding audio event (subclip)...");
                                aEvent = aTrack.AddAudioEvent(cursor, length);
                                DowPImporterModule.Log($"Getting audio stream (subclip)...");
                                AudioStream aStream = media.GetAudioStreamByIndex(0);
                                DowPImporterModule.Log($"Adding take to audio event (subclip)...");
                                Take take = aEvent.AddTake(aStream);
                                take.Offset = Timecode.FromSeconds(inSec);
                                DowPImporterModule.Log($"Take added.");
                            }

                            if (vEvent != null && aEvent != null)
                            {
                                DowPImporterModule.Log($"Grouping events (subclip)...");
                                TrackEventGroup group = new TrackEventGroup();
                                myVegas.Project.Groups.Add(group);
                                group.Add(vEvent);
                                group.Add(aEvent);
                            }

                            DowPImporterModule.Log($"Updating cursor position (subclip)...");
                            myVegas.UpdateUI();
                            myVegas.Transport.CursorPosition = cursor + length;
                        } catch (Exception ex) {
                            DowPImporterModule.Log($"Exception in subclip timeline insertion: {ex.Message}\n{ex.StackTrace}");
                            throw;
                        }
                    }

                    imported++;
                }
            }
            return imported;
        }

        private bool TrackHasSpace(Track track, Timecode insertStart, Timecode insertLength)
        {
            Timecode insertEnd = insertStart + insertLength;
            foreach (TrackEvent ev in track.Events)
            {
                Timecode evEnd = ev.Start + ev.Length;
                if (ev.Start < insertEnd && evEnd > insertStart)
                {
                    return false;
                }
            }
            return true;
        }

        private VideoTrack GetOrCreateVideoTrack(Timecode insertStart, Timecode insertLength)
        {
            foreach (Track t in myVegas.Project.Tracks)
            {
                if (t.IsVideo() && t.Selected && TrackHasSpace(t, insertStart, insertLength))
                {
                    return (VideoTrack)t;
                }
            }
            foreach (Track t in myVegas.Project.Tracks)
            {
                if (t.IsVideo() && TrackHasSpace(t, insertStart, insertLength))
                {
                    return (VideoTrack)t;
                }
            }
            VideoTrack newTrack = new VideoTrack(myVegas.Project.Tracks.Count, "DowP Video");
            myVegas.Project.Tracks.Add(newTrack);
            return newTrack;
        }

        private AudioTrack GetOrCreateAudioTrack(Timecode insertStart, Timecode insertLength)
        {
            foreach (Track t in myVegas.Project.Tracks)
            {
                if (t.IsAudio() && t.Selected && TrackHasSpace(t, insertStart, insertLength))
                {
                    return (AudioTrack)t;
                }
            }
            foreach (Track t in myVegas.Project.Tracks)
            {
                if (t.IsAudio() && TrackHasSpace(t, insertStart, insertLength))
                {
                    return (AudioTrack)t;
                }
            }
            AudioTrack newTrack = new AudioTrack(myVegas.Project.Tracks.Count, "DowP Audio");
            myVegas.Project.Tracks.Add(newTrack);
            return newTrack;
        }

        private bool IsImageFile(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            return ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp" ||
                   ext == ".bmp" || ext == ".gif" || ext == ".tiff" || ext == ".avif";
        }

        public async void SendSelectionToDowP()
        {
            try
            {
                if (myVegas.Project == null)
                {
                    myControl.SetLog("No hay ningún proyecto abierto en VEGAS.");
                    return;
                }

                List<object> items = new List<object>();

                // 1. Buscar clips seleccionados en la línea de tiempo
                foreach (Track track in myVegas.Project.Tracks)
                {
                    foreach (TrackEvent ev in track.Events)
                    {
                        if (ev.Selected && ev.ActiveTake != null && ev.ActiveTake.Media != null)
                        {
                            string path = ev.ActiveTake.Media.FilePath;
                            double inSec = ev.ActiveTake.Offset.ToMilliseconds() / 1000.0;
                            double outSec = (ev.ActiveTake.Offset + ev.Length).ToMilliseconds() / 1000.0;

                            items.Add(new
                            {
                                path = path,
                                name = ev.ActiveTake.Name ?? Path.GetFileName(path),
                                hasTrim = true,
                                @in = inSec,
                                @out = outSec
                            });
                        }
                    }
                }

                if (items.Count == 0)
                {
                    myControl.SetLog("No hay ningún evento seleccionado en el timeline.");
                    return;
                }

                string json = jsonSerializer.Serialize(new
                {
                    items = items,
                    appIdentifier = "vegas"
                });

                StringContent content = new StringContent(json, Encoding.UTF8, "application/json");
                HttpResponseMessage response = await httpClient.PostAsync($"http://127.0.0.1:{DowPPort}/api/vegas/push", content);

                if (response.IsSuccessStatusCode)
                {
                    myControl.SetLog($"📤 {items.Count} clip(s) enviado(s) a DowP.");
                }
                else
                {
                    myControl.SetLog($"Error al enviar a DowP: {response.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                myControl.SetLinkedState(false, false, "No se pudo conectar con DowP: " + ex.Message);
            }
        }

        public async void ToggleLinkDowP()
        {
            try
            {
                var payload = new { toggle = true };
                string json = jsonSerializer.Serialize(payload);
                StringContent content = new StringContent(json, Encoding.UTF8, "application/json");
                HttpResponseMessage resp = await httpClient.PostAsync($"http://127.0.0.1:{DowPPort}/api/vegas/link", content);
                if (resp.IsSuccessStatusCode)
                {
                    string respBody = await resp.Content.ReadAsStringAsync();
                    var dict = jsonSerializer.Deserialize<Dictionary<string, object>>(respBody);
                    bool isLinked = dict != null && dict.ContainsKey("isLinked") && Convert.ToBoolean(dict["isLinked"]);
                    myControl.SetLinkedState(true, isLinked, isLinked ? "Vinculado como editor activo." : "Desvinculado.");
                }
                else
                {
                    myControl.SetLinkedState(false, false, "DowP no responde.");
                }
            }
            catch
            {
                myControl.SetLinkedState(false, false, "DowP 2 no está abierto o no responde.");
            }
        }

        public async void CheckDowPConnection()
        {
            try
            {
                HttpResponseMessage resp = await httpClient.GetAsync($"http://127.0.0.1:{DowPPort}/api/vegas/status");
                if (resp.IsSuccessStatusCode)
                {
                    string respBody = await resp.Content.ReadAsStringAsync();
                    var dict = jsonSerializer.Deserialize<Dictionary<string, object>>(respBody);
                    bool isLinked = dict != null && dict.ContainsKey("isLinked") && Convert.ToBoolean(dict["isLinked"]);
                    myControl.SetLinkedState(true, isLinked, isLinked ? "Vinculado con DowP." : "Conectado – Sin vincular.");
                }
                else
                {
                    myControl.SetLinkedState(false, false, "DowP no responde.");
                }
            }
            catch
            {
                myControl.SetLinkedState(false, false, "DowP 2 no está abierto.");
            }
        }

        private string ReadRequestBody(HttpListenerRequest req)
        {
            using (var reader = new StreamReader(req.InputStream, req.ContentEncoding))
            {
                return reader.ReadToEnd();
            }
        }

        private void WriteJsonResponse(HttpListenerResponse res, object data, int statusCode)
        {
            res.ContentType = "application/json; charset=utf-8";
            res.StatusCode = statusCode;
            string json = jsonSerializer.Serialize(data);
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            res.ContentLength64 = bytes.Length;
            res.OutputStream.Write(bytes, 0, bytes.Length);
            res.Close();
        }
    }
}
