using System;
using System.Collections;
using System.IO;
using System.Reflection;
using ScriptPortal.Vegas;

namespace DowPImporter
{
    public class DowPImporterModule : ICustomCommandModule
    {
        private Vegas myVegas = null;
        private CustomCommand myCommand = null;
        private DowPDockableControl myDockView = null;
        private VegasImporterBridge myBridge = null;
        private const string DockViewInstanceName = "DowPImporterDock";

        public static void Log(string message)
        {
            try
            {
                string logFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DowP_VegasExtension.log");
                File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}\r\n");
            }
            catch { }
        }

        static DowPImporterModule()
        {
            Log("Static constructor invoked");
            AppDomain.CurrentDomain.AssemblyResolve += (sender, args) =>
            {
                if (args.Name.StartsWith("ScriptPortal.Vegas"))
                {
                    foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
                    {
                        if (asm.GetName().Name == "ScriptPortal.Vegas")
                            return asm;
                    }
                }
                return null;
            };
        }

        public void InitializeModule(Vegas vegas)
        {
            Log("InitializeModule called");
            try
            {
                myVegas = vegas;
                Log("InitializeModule finished successfully");
            }
            catch (Exception ex)
            {
                Log("InitializeModule ERROR: " + ex.ToString());
            }
        }

        public ICollection GetCustomCommands()
        {
            Log("GetCustomCommands called");
            try
            {
                myCommand = new CustomCommand(CommandCategory.View, "DowPImporter")
                {
                    DisplayName = "DowP Importer"
                };
                myCommand.Invoked += HandleInvoked;
                myCommand.MenuPopup += HandleMenuPopup;

                return new CustomCommand[] { myCommand };
            }
            catch (Exception ex)
            {
                Log("GetCustomCommands ERROR: " + ex.ToString());
                return new CustomCommand[0];
            }
        }

        private void HandleInvoked(object sender, EventArgs e)
        {
            Log("HandleInvoked: Activating dock view");
            try
            {
                if (myVegas == null)
                    return;

                // VEGAS keeps dock views by their instance name.  Re-activate an
                // existing view instead of trying to load a control a second time.
                if (myVegas.ActivateDockView(DockViewInstanceName))
                {
                    return;
                }

                myBridge?.Stop();
                myDockView = new DowPDockableControl(myVegas);
                myDockView.AutoLoadCommand = myCommand;
                myDockView.PersistDockWindowState = true;
                myVegas.LoadDockView(myDockView);

                // The bridge is started only after VEGAS has parented the control.
                // This guarantees a real UI handle for cross-thread UI marshaling.
                myBridge = new VegasImporterBridge(myVegas, myDockView);
                myBridge.Start();
                Log("Dock view loaded and bridge started");
            }
            catch (Exception ex)
            {
                Log("HandleInvoked ERROR: " + ex.ToString());
            }
        }

        private void HandleMenuPopup(object sender, EventArgs e)
        {
            try
            {
                myCommand.Checked = myVegas != null && myVegas.FindDockView(DockViewInstanceName);
            }
            catch (Exception ex)
            {
                Log("HandleMenuPopup ERROR: " + ex.Message);
            }
        }
    }
}
