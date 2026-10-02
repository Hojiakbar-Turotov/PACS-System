using System;
using System.IO;
using System.Diagnostics;
using System.Threading;
using System.Drawing;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SabadarmonPACS
{
    static class Program
    {
        private const string MUTEX_NAME = "SabadarmonPACSServerMutex_2026";
        private const string SERVER_URL = "http://localhost:8000";

        private static readonly object logLock = new object();
        public static void SafeLog(string msg)
        {
            try
            {
                lock (logLock)
                {
                    string dir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data", "logs");
                    if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                    string path = Path.Combine(dir, "launcher.log");
                    using (FileStream fs = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                    using (StreamWriter sw = new StreamWriter(fs))
                    {
                        sw.WriteLine(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + msg);
                    }
                }
            }
            catch { }
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            try
            {
                bool createdNew;
                using (Mutex mutex = new Mutex(true, MUTEX_NAME, out createdNew))
                {
                    SafeLog("[MAIN] Boshlandi. Args: " + string.Join(" ", args) + ", createdNew: " + createdNew);

                    if (!createdNew)
                    {
                        SafeLog("[MAIN] Dastur allaqachon fonda ishlamoqda. Veb-panel ochilmoqda.");
                        OpenBrowser(SERVER_URL);
                        return;
                    }

                    TrayApp app = new TrayApp(args);
                    Application.Run();
                }
            }
            catch (Exception ex)
            {
                SafeLog("[MAIN_FATAL] " + ex.ToString());
            }
        }

        public static void OpenBrowser(string url)
        {
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch
            {
                try { Process.Start("explorer.exe", url); } catch { }
            }
        }
    }

    public class TrayApp
    {
        private const string RUN_KEY = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string APP_NAME = "SabadarmonPACS";
        private const string SERVER_URL = "http://localhost:8000";

        private NotifyIcon trayIcon;
        private ContextMenuStrip contextMenu;
        private Process serverProcess = null;
        private string baseDir;
        private System.Windows.Forms.Timer healthTimer;

        public TrayApp(string[] args)
        {
            try
            {
                baseDir = AppDomain.CurrentDomain.BaseDirectory;

                bool isBackground = false;
                foreach (string arg in args)
                {
                    if (arg.Equals("--background", StringComparison.OrdinalIgnoreCase) || arg.Equals("-b", StringComparison.OrdinalIgnoreCase))
                    {
                        isBackground = true;
                    }
                }

                // 1. Windows avtomatik yuklanishiga qo'shish
                EnsureStartupRegistered();

                // 2. Tray Icon va menyusini yaratish
                InitializeTray();

                // 3. PACS Serverni ishga tushirish
                StartServerProcess();

                // 4. Sog'liq tekshiruvi (har 15s)
                healthTimer = new System.Windows.Forms.Timer();
                healthTimer.Interval = 15000;
                healthTimer.Tick += (s, e) => CheckServerHealth();
                healthTimer.Start();

                // 5. Agar qo'lda ochilgan bo'lsa brauzerda panelni ochish
                if (!isBackground)
                {
                    Program.OpenBrowser(SERVER_URL);
                }

                try
                {
                    trayIcon.ShowBalloonTip(3000, "Sabadarmon MSKT PACS", "PACS Server va GE CT monitoring orqa fonda faol.", ToolTipIcon.Info);
                }
                catch { }

                Program.SafeLog("[TRAY] Muvaffaqiyatli ishga tushdi va faol.");
            }
            catch (Exception ex)
            {
                Program.SafeLog("[TRAY_ERROR] " + ex.ToString());
            }
        }

        private void InitializeTray()
        {
            try
            {
                contextMenu = new ContextMenuStrip();

                var titleItem = new ToolStripMenuItem("Sabadarmon MSKT PACS (:8000)");
                titleItem.Enabled = false;
                contextMenu.Items.Add(titleItem);

                var copyrightItem = new ToolStripMenuItem("Huquqlar FrunzaDev tomonidan himoyalangan");
                copyrightItem.Enabled = false;
                copyrightItem.Font = new Font(contextMenu.Font.FontFamily, 7.5f, FontStyle.Italic);
                contextMenu.Items.Add(copyrightItem);

                contextMenu.Items.Add(new ToolStripSeparator());

                var openWebItem = new ToolStripMenuItem("Boshqaruv paneli (Web)", null, (s, e) => Program.OpenBrowser(SERVER_URL));
                contextMenu.Items.Add(openWebItem);

                contextMenu.Items.Add(new ToolStripMenuItem("Bugungi navbat (/list)", null, (s, e) => Program.OpenBrowser(SERVER_URL + "/list")));
                contextMenu.Items.Add(new ToolStripMenuItem("Sozlamalar (Settings)", null, (s, e) => Program.OpenBrowser(SERVER_URL + "#settings")));

                contextMenu.Items.Add(new ToolStripSeparator());

                var restartItem = new ToolStripMenuItem("Serverni qayta ishga tushirish", null, (s, e) => RestartServer());
                contextMenu.Items.Add(restartItem);

                var autoStartItem = new ToolStripMenuItem("Windows bilan birga ishga tushish");
                autoStartItem.CheckOnClick = true;
                autoStartItem.Checked = IsStartupRegistered();
                autoStartItem.Click += (s, e) => ToggleStartup(autoStartItem.Checked);
                contextMenu.Items.Add(autoStartItem);

                contextMenu.Items.Add(new ToolStripSeparator());

                var exitItem = new ToolStripMenuItem("Chiqish va Dasturni to'xtatish", null, (s, e) => ExitApplication());
                contextMenu.Items.Add(exitItem);

                trayIcon = new NotifyIcon();
                trayIcon.Text = "Sabadarmon PACS (:8000) - FrunzaDev";
                
                string iconPath = Path.Combine(baseDir, "assets", "app.ico");
                if (File.Exists(iconPath))
                {
                    try { trayIcon.Icon = new Icon(iconPath); }
                    catch { trayIcon.Icon = SystemIcons.Application; }
                }
                else
                {
                    trayIcon.Icon = SystemIcons.Application;
                }

                trayIcon.ContextMenuStrip = contextMenu;
                trayIcon.Visible = true;
                trayIcon.DoubleClick += (s, e) => Program.OpenBrowser(SERVER_URL);
            }
            catch (Exception ex)
            {
                Program.SafeLog("[TRAY_INIT_ERROR] " + ex.ToString());
            }
        }

        private void StartServerProcess()
        {
            try
            {
                if (serverProcess != null && !serverProcess.HasExited)
                {
                    Program.SafeLog("[SERVER] Server allaqachon faol (PID: " + serverProcess.Id + ")");
                    return;
                }

                string pythonPath = FindPython(baseDir);
                string scriptPath = Path.Combine(baseDir, "run_server.py");

                if (!File.Exists(scriptPath))
                {
                    Program.SafeLog("[SERVER_ERROR] run_server.py topilmadi: " + scriptPath);
                    return;
                }

                if (string.IsNullOrEmpty(pythonPath) || !File.Exists(pythonPath))
                {
                    Program.SafeLog("[SERVER_ERROR] Python topilmadi: " + pythonPath);
                    return;
                }

                Program.SafeLog("[SERVER] Ishga tushirilmoqda: " + pythonPath + " " + scriptPath);

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = pythonPath;
                psi.Arguments = "\"" + scriptPath + "\"";
                psi.WorkingDirectory = baseDir;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;

                serverProcess = Process.Start(psi);
                Program.SafeLog("[SERVER] Ishga tushdi, PID: " + (serverProcess != null ? serverProcess.Id.ToString() : "null"));
            }
            catch (Exception ex)
            {
                Program.SafeLog("[SERVER_ERROR] " + ex.ToString());
            }
        }

        private void CheckServerHealth()
        {
            try
            {
                if (serverProcess == null || serverProcess.HasExited)
                {
                    Program.SafeLog("[HEALTH] Server to'xtab qolgan, qayta ishga tushirilmoqda...");
                    StartServerProcess();
                }
            }
            catch { }
        }

        private void RestartServer()
        {
            StopServerProcess();
            Thread.Sleep(1000);
            StartServerProcess();
            try { trayIcon.ShowBalloonTip(2000, "Sabadarmon PACS", "Server qayta ishga tushirildi.", ToolTipIcon.Info); } catch { }
        }

        private void StopServerProcess()
        {
            try
            {
                if (serverProcess != null && !serverProcess.HasExited)
                {
                    serverProcess.Kill();
                    serverProcess.WaitForExit(2000);
                }
            }
            catch { }

            try
            {
                ProcessStartInfo wmiPsi = new ProcessStartInfo("powershell", 
                    "-NoProfile -Command \"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }\"")
                {
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    UseShellExecute = false
                };
                var p = Process.Start(wmiPsi);
                p.WaitForExit(3000);
            }
            catch { }
        }

        private void ExitApplication()
        {
            DialogResult dr = MessageBox.Show(
                "Sabadarmon PACS tizimidan chiqmoqchimisiz?\n\nChiqilsa, KT apparatidan avtomatik tasvirlarni olish va Telegramga yuklash to'xtatiladi.",
                "Dasturni to'xtatish",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question);

            if (dr == DialogResult.Yes)
            {
                Program.SafeLog("[EXIT] Foydalanuvchi chiqishni tanladi.");

                if (healthTimer != null)
                {
                    healthTimer.Stop();
                    healthTimer.Dispose();
                }

                StopServerProcess();

                if (trayIcon != null)
                {
                    trayIcon.Visible = false;
                    trayIcon.Dispose();
                }

                Application.Exit();
            }
        }

        private string FindPython(string baseDir)
        {
            string localPython = Path.Combine(baseDir, "python", "python.exe");
            if (File.Exists(localPython)) return localPython;

            string py311 = @"C:\Python311\python.exe";
            if (File.Exists(py311)) return py311;

            string py311w = @"C:\Python311\pythonw.exe";
            if (File.Exists(py311w)) return py311w;

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string userPy = Path.Combine(localAppData, @"Programs\Python\Python311\python.exe");
            if (File.Exists(userPy)) return userPy;

            return "python.exe";
        }

        private bool IsStartupRegistered()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RUN_KEY, false))
                {
                    if (key != null)
                    {
                        var val = key.GetValue(APP_NAME);
                        return val != null;
                    }
                }
            }
            catch { }
            return false;
        }

        private void EnsureStartupRegistered()
        {
            if (!IsStartupRegistered())
            {
                ToggleStartup(true);
            }
        }

        private void ToggleStartup(bool enable)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RUN_KEY, true))
                {
                    if (key != null)
                    {
                        if (enable)
                        {
                            string exePath = Application.ExecutablePath;
                            string val = "\"" + exePath + "\" --background";
                            key.SetValue(APP_NAME, val);
                        }
                        else
                        {
                            key.DeleteValue(APP_NAME, false);
                        }
                    }
                }
            }
            catch { }
        }
    }
}
