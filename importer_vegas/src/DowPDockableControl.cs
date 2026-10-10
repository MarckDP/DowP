using System;
using System.Drawing;
using System.Windows.Forms;
using ScriptPortal.Vegas;

namespace DowPImporter
{
    public class DowPDockableControl : DockableControl
    {
        // Controles de interfaz
        private Panel pnlStatusDot;
        private Label lblConnection;
        private Button btnLaunchDowP;
        private Button btnCheckConnection;
        private Button btnSendToDowP;
        private CheckBox chkAddToTimeline;
        private CheckBox chkImportImages;
        private Label lblLog;
        private ToolTip toolTip;

        public bool AddToTimeline => chkAddToTimeline.Checked;
        public bool ImportImages => chkImportImages.Checked;
        public bool IsConnected { get; private set; }
        public bool IsLinked { get; private set; }

        public event EventHandler SendToDowPRequested;
        public event EventHandler ToggleLinkRequested;

        private readonly Vegas appVegas;

        public DowPDockableControl(Vegas vegas) : base("DowPImporterDock")
        {
            appVegas = vegas;
            DisplayName = "DowP Importer";
            DefaultDockWindowStyle = DockWindowStyle.Docked;
            DefaultFloatingSize = new Size(300, 260);
            MinimumSize = new Size(260, 220);

            InitializeUI();
        }

        private void InitializeUI()
        {
            // Tooltip manager global
            toolTip = new ToolTip();

            // Configuración del contenedor principal
            BackColor = Color.FromArgb(30, 30, 30);
            ForeColor = Color.FromArgb(225, 225, 225);
            Font = new Font("Segoe UI", 9F, FontStyle.Regular);
            AutoScroll = true;

            FlowLayoutPanel flow = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                FlowDirection = FlowDirection.TopDown,
                WrapContents = false,
                Padding = new Padding(12),
                AutoScroll = true,
                BackColor = BackColor,
                AutoSize = false
            };

            // Barra superior de estado
            FlowLayoutPanel statusRow = new FlowLayoutPanel
            {
                FlowDirection = FlowDirection.LeftToRight,
                WrapContents = false,
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 10)
            };

            pnlStatusDot = new Panel
            {
                Size = new Size(12, 12),
                Margin = new Padding(2, 4, 8, 0),
                BackColor = Color.FromArgb(231, 76, 60) // Rojo desconectado inicial
            };
            pnlStatusDot.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (Brush b = new SolidBrush(pnlStatusDot.BackColor))
                {
                    e.Graphics.FillEllipse(b, 0, 0, 11, 11);
                }
            };

            lblConnection = new Label
            {
                Text = "Desconectado de DowP",
                AutoSize = true,
                Font = new Font("Segoe UI", 9F, FontStyle.Bold),
                ForeColor = Color.FromArgb(200, 200, 200)
            };
            statusRow.Controls.Add(pnlStatusDot);
            statusRow.Controls.Add(lblConnection);
            flow.Controls.Add(statusRow);

            // Barra de botones de acción
            FlowLayoutPanel actionRow = new FlowLayoutPanel
            {
                FlowDirection = FlowDirection.LeftToRight,
                WrapContents = false,
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 12)
            };

            btnLaunchDowP = CreateIconButton("power", "Abrir DowP", (s, e) => LaunchDowP());
            btnCheckConnection = CreateIconButton("link", "Comprobar / Vincular conexión con DowP", (s, e) => ToggleLinkRequested?.Invoke(this, EventArgs.Empty));
            btnSendToDowP = CreateIconButton("send", "Enviar clips seleccionados a DowP", (s, e) => SendToDowPRequested?.Invoke(this, EventArgs.Empty));

            actionRow.Controls.Add(btnLaunchDowP);
            actionRow.Controls.Add(btnCheckConnection);
            actionRow.Controls.Add(btnSendToDowP);
            flow.Controls.Add(actionRow);

            // Checkboxes de configuración
            chkAddToTimeline = CreateThemedCheckBox("Añadir a línea de tiempo activa", true);
            chkImportImages = CreateThemedCheckBox("Añadir imágenes a línea de tiempo", true);

            flow.Controls.Add(chkAddToTimeline);
            flow.Controls.Add(chkImportImages);

            // Mensaje informativo / Log
            lblLog = new Label
            {
                Text = "Listo. Esperando conexión con DowP...",
                AutoSize = false,
                Size = new Size(240, 48),
                ForeColor = Color.FromArgb(160, 160, 160),
                Margin = new Padding(0, 8, 0, 0)
            };
            flow.Controls.Add(lblLog);

            Controls.Add(flow);
        }

        private RoundedButton CreateIconButton(string iconName, string tooltip, EventHandler onClick)
        {
            RoundedButton btn = new RoundedButton
            {
                Size = new Size(38, 38),
                Cursor = Cursors.Hand,
                Margin = new Padding(0, 0, 8, 0)
            };
            Image img = SvgIcons.GetImage(iconName);
            if (img != null)
            {
                btn.Image = img;
            }
            else
            {
                btn.Text = iconName;
                btn.ForeColor = Color.White;
                btn.Font = new Font("Segoe UI Emoji", 12F);
            }

            toolTip.SetToolTip(btn, tooltip);

            if (onClick != null) btn.Click += onClick;
            return btn;
        }

        private CheckBox CreateThemedCheckBox(string text, bool defaultValue)
        {
            return new CheckBox
            {
                Text = text,
                Checked = defaultValue,
                AutoSize = true,
                ForeColor = Color.FromArgb(220, 220, 220),
                Font = new Font("Segoe UI", 9F),
                Cursor = Cursors.Hand,
                Margin = new Padding(0, 0, 0, 6)
            };
        }

        public void SetLinkedState(bool isConnected, bool isLinked, string message = null)
        {
            if (InvokeRequired)
            {
                Invoke(new Action(() => SetLinkedState(isConnected, isLinked, message)));
                return;
            }

            IsConnected = isConnected;
            IsLinked = isConnected && isLinked;

            if (!isConnected)
            {
                pnlStatusDot.BackColor = Color.FromArgb(231, 76, 60); // Rojo
                lblConnection.Text = "Desconectado de DowP";
                lblConnection.ForeColor = Color.FromArgb(231, 76, 60);
                btnCheckConnection.Text = "";
                btnCheckConnection.Image = SvgIcons.GetImage("link");
                btnCheckConnection.BackColor = Color.FromArgb(45, 45, 48);
                toolTip.SetToolTip(btnCheckConnection, "DowP no está abierto (haz clic para conectar)");
            }
            else if (!isLinked)
            {
                pnlStatusDot.BackColor = Color.FromArgb(241, 196, 15); // Amarillo
                lblConnection.Text = "Conectado – Sin vincular";
                lblConnection.ForeColor = Color.FromArgb(241, 196, 15);
                btnCheckConnection.Text = "";
                btnCheckConnection.Image = SvgIcons.GetImage("link");
                btnCheckConnection.BackColor = Color.FromArgb(45, 45, 48);
                toolTip.SetToolTip(btnCheckConnection, "Conectado a DowP – Haz clic para vincular");
            }
            else
            {
                pnlStatusDot.BackColor = Color.FromArgb(46, 204, 113); // Verde
                lblConnection.Text = "Vinculado con DowP";
                lblConnection.ForeColor = Color.FromArgb(46, 204, 113);
                btnCheckConnection.Text = "";
                btnCheckConnection.Image = SvgIcons.GetImage("check_circle");
                btnCheckConnection.BackColor = Color.FromArgb(30, 80, 50);
                toolTip.SetToolTip(btnCheckConnection, "Vinculado con DowP – Haz clic para desvincular");
            }

            pnlStatusDot.Invalidate();

            if (!string.IsNullOrEmpty(message))
            {
                lblLog.Text = message;
            }
        }

        public void SetConnectionState(bool connected, string message = null)
        {
            SetLinkedState(connected, connected ? IsLinked : false, message);
        }

        public void SetLog(string message)
        {
            if (InvokeRequired)
            {
                Invoke(new Action(() => SetLog(message)));
                return;
            }
            lblLog.Text = message;
        }

        private void LaunchDowP()
        {
            try
            {
                string targetExe = null;

                // 1. Intentar leer desde el registro (Inno Setup)
                try
                {
                    using (Microsoft.Win32.RegistryKey key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\{ED4B4BD2-DCD4-4496-866F-94322AC0A7C8}_is1"))
                    {
                        if (key != null)
                        {
                            object installLocation = key.GetValue("InstallLocation");
                            if (installLocation != null)
                            {
                                string candidateRegistry = System.IO.Path.Combine(installLocation.ToString(), "DowP.exe");
                                if (System.IO.File.Exists(candidateRegistry))
                                {
                                    targetExe = candidateRegistry;
                                }
                            }
                        }
                    }
                }
                catch { }

                // 2. Rutas por defecto si no se encontró en el registro
                if (string.IsNullOrEmpty(targetExe))
                {
                    string appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                    string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
                    string candidate1 = System.IO.Path.Combine(appData, "Programs", "DowP", "DowP.exe");
                    string candidate2 = System.IO.Path.Combine(programFiles, "DowP", "DowP.exe");

                    if (System.IO.File.Exists(candidate1)) targetExe = candidate1;
                    else if (System.IO.File.Exists(candidate2)) targetExe = candidate2;
                }

                if (!string.IsNullOrEmpty(targetExe))
                {
                    System.Diagnostics.Process.Start(targetExe);
                    SetLog("Lanzando DowP...");
                }
                else
                {
                    SetLog("DowP no encontrado en rutas estándar.");
                }
            }
            catch (Exception ex)
            {
                SetLog("Error al lanzar DowP: " + ex.Message);
            }
        }

        private class RoundedButton : Button
        {
            public Color NormalColor { get; set; } = Color.FromArgb(45, 45, 48);
            public Color HoverColor { get; set; } = Color.FromArgb(63, 63, 70);
            public Color DownColor { get; set; } = Color.FromArgb(0, 122, 204);

            private bool isHovered = false;
            private bool isDown = false;

            public RoundedButton()
            {
                FlatStyle = FlatStyle.Flat;
                FlatAppearance.BorderSize = 0;
                BackColor = NormalColor;
            }

            protected override void OnMouseEnter(EventArgs e) { isHovered = true; BackColor = HoverColor; base.OnMouseEnter(e); Invalidate(); }
            protected override void OnMouseLeave(EventArgs e) { isHovered = false; BackColor = NormalColor; base.OnMouseLeave(e); Invalidate(); }
            protected override void OnMouseDown(MouseEventArgs e) { isDown = true; BackColor = DownColor; base.OnMouseDown(e); Invalidate(); }
            protected override void OnMouseUp(MouseEventArgs e) { isDown = false; BackColor = isHovered ? HoverColor : NormalColor; base.OnMouseUp(e); Invalidate(); }

            protected override void OnPaint(PaintEventArgs e)
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                if (Parent != null)
                {
                    e.Graphics.Clear(Parent.BackColor);
                }

                Rectangle rect = new Rectangle(0, 0, Width - 1, Height - 1);
                int radius = 10;
                using (System.Drawing.Drawing2D.GraphicsPath path = new System.Drawing.Drawing2D.GraphicsPath())
                {
                    path.AddArc(rect.X, rect.Y, radius, radius, 180, 90);
                    path.AddArc(rect.Right - radius, rect.Y, radius, radius, 270, 90);
                    path.AddArc(rect.Right - radius, rect.Bottom - radius, radius, radius, 0, 90);
                    path.AddArc(rect.X, rect.Bottom - radius, radius, radius, 90, 90);
                    path.CloseFigure();

                    using (SolidBrush brush = new SolidBrush(BackColor))
                    {
                        e.Graphics.FillPath(brush, path);
                    }
                }

                if (Image != null)
                {
                    int imgX = (Width - Image.Width) / 2;
                    int imgY = (Height - Image.Height) / 2;
                    e.Graphics.DrawImage(Image, imgX, imgY);
                }
            }
        }
    }
}
