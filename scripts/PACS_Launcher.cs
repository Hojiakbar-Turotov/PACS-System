using System;
using System.IO;
using System.Diagnostics;
using System.Net.Sockets;
using System.Threading;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SabadarmonPACS
{
    static class Program
    {
        private const string RUN_KEY = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string APP_NAME = "SabadarmonPACS";
        private const int SERVER_PORT = 8000;
        private const string SERVER_URL = "http://localhost:8000";
        private const string MUTEX_NAME = "Global\\SabadarmonPACSServerMutex_2026";

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool createdNew;
            using (Mutex mutex = new Mutex(true, MUTEX_NAME, out createdNew))
            {
                if (!createdNew)
                {
                    // Dastur allaqachon fonda ishlamoqda, brauzerda panelni ochamiz
                    OpenBrowser(SERVER_URL);
                    return;
                }

                Application.Run(new TrayApplicationContext(args));
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

    public class TrayApplicationContext : ApplicationContext
    {
        private const string RUN_KEY = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string APP_NAME = "SabadarmonPACS";
        private const int SERVER_PORT = 8000;
        private const string SERVER_URL = "http://localhost:8000";

        private NotifyIcon trayIcon;
        private ContextMenuStrip contextMenu;
        private Process serverProcess = null;
        private string baseDir;
        private System.Windows.Forms.Timer healthTimer;

        public TrayApplicationContext(string[] args)
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

            // 1. Windows avtomatik ishga tushishini ta'minlash
            EnsureStartupRegistered();

            // 2. Tray Icon va menyusini yaratish
            InitializeTray();

            // 3. PACS Server jarayonini ishga tushirish
            StartServerProcess();

            // 4. Server sog'ligini kuzatish taymeri (har 10 soniyada)
            healthTimer = new System.Windows.Forms.Timer();
            healthTimer.Interval = 10000;
            healthTimer.Tick += (s, e) => CheckServerHealth();
            healthTimer.Start();

            // 5. Agar qo'lda ochilgan bo'lsa, brauzerni avtomatik ochish
            if (!isBackground)
            {
                Program.OpenBrowser(SERVER_URL);
            }

            // Tray bildirishnomasi
            trayIcon.ShowBalloonTip(3000, "Sabadarmon MSKT PACS", "PACS Server va GE CT monitoring orqa fonda ishga tushdi (Port 8000).", ToolTipIcon.Info);
        }

        private void InitializeTray()
        {
            contextMenu = new ContextMenuStrip();
            contextMenu.Font = new Font("Segoe UI", 9.25f);

            var titleItem = new ToolStripMenuItem("🏥 Sabadarmon MSKT PACS");
            titleItem.Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            titleItem.Enabled = false;
            contextMenu.Items.Add(titleItem);

            contextMenu.Items.Add(new ToolStripSeparator());

            var openWebItem = new ToolStripMenuItem("🌐 Boshqaruv paneli (localhost:8000)", null, (s, e) => Program.OpenBrowser(SERVER_URL));
            openWebItem.Font = new Font("Segoe UI", 9.25f, FontStyle.Bold);
            contextMenu.Items.Add(openWebItem);

            contextMenu.Items.Add(new ToolStripMenuItem("📋 Bugungi navbat (/list)", null, (s, e) => Program.OpenBrowser(SERVER_URL + "/list")));
            contextMenu.Items.Add(new ToolStripMenuItem("⚙️ Sozlamalar", null, (s, e) => Program.OpenBrowser(SERVER_URL + "#settings")));

            contextMenu.Items.Add(new ToolStripSeparator());

            var restartItem = new ToolStripMenuItem("🔄 Serverni qayta ishga tushirish", null, (s, e) => RestartServer());
            contextMenu.Items.Add(restartItem);

            var autoStartItem = new ToolStripMenuItem("🖥️ Windows bilan birga ishga tushish");
            autoStartItem.CheckOnClick = true;
            autoStartItem.Checked = IsStartupRegistered();
            autoStartItem.Click += (s, e) => ToggleStartup(autoStartItem.Checked);
            contextMenu.Items.Add(autoStartItem);

            contextMenu.Items.Add(new ToolStripSeparator());

            var exitItem = new ToolStripMenuItem("❌ Chiqish va Dasturni to'xtatish", null, (s, e) => ExitApplication());
            exitItem.ForeColor = Color.DarkRed;
            contextMenu.Items.Add(exitItem);

            trayIcon = new NotifyIcon();
            trayIcon.Text = "Sabadarmon MSKT PACS (Port: 8000)";
            trayIcon.Icon = GenerateAppIcon();
            trayIcon.ContextMenuStrip = contextMenu;
            trayIcon.Visible = true;
            trayIcon.DoubleClick += (s, e) => Program.OpenBrowser(SERVER_URL);
        }

        private Icon GenerateAppIcon()
        {
            try
            {
                // Professional ko'k fonli tibbiy xoch ikonkasini GDI+ da chizamiz
                using (Bitmap bmp = new Bitmap(32, 32))
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.Clear(Color.Transparent);

                    // Ko'k doira fon
                    using (Brush bgBrush = new SolidBrush(Color.FromArgb(14, 116, 144))) // Tibbiy to'q firuza/ko'k
                    {
                        g.FillEllipse(bgBrush, 1, 1, 30, 30);
                    }

                    // Cheti uchun yengil hoshiya
                    using (Pen pen = new Pen(Color.FromArgb(6, 182, 212), 2))
                    {
                        g.DrawEllipse(pen, 2, 2, 28, 28);
                    }

                    // Oq rangli tibbiy xoch
                    using (Brush crossBrush = new SolidBrush(Color.White))
                    {
                        // Vertikal chiziq
                        g.FillRectangle(crossBrush, 13, 7, 6, 18);
                        // Gorizontal chiziq
                        g.FillRectangle(crossBrush, 7, 13, 18, 6);
                    }

                    IntPtr hIcon = bmp.GetHicon();
                    return Icon.FromHandle(hIcon);
                }
            }
            catch
            {
                return SystemIcons.Application;
            }
        }

        private void StartServerProcess()
        {
            if (IsPortOpen("127.0.0.1", SERVER_PORT, 400))
            {
                return; // Server allaqachon ishlayapti
            }

            string pythonPath = FindPython(baseDir);
            string scriptPath = Path.Combine(baseDir, "run_server.py");

            if (!File.Exists(scriptPath))
            {
                MessageBox.Show("run_server.py topilmadi: " + scriptPath, "PACS Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            if (string.IsNullOrEmpty(pythonPath) || !File.Exists(pythonPath))
            {
                MessageBox.Show("Python topilmadi! C:\\Python311 o'rnatilganligini tekshiring.", "PACS Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = pythonPath;
                psi.Arguments = "\"" + scriptPath + "\"";
                psi.WorkingDirectory = baseDir;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;

                serverProcess = Process.Start(psi);

                // Port ochilishini kutamiz (5 soniya)
                for (int i = 0; i < 25; i++)
                {
                    Thread.Sleep(200);
                    if (IsPortOpen("127.0.0.1", SERVER_PORT, 200))
                    {
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("PACS serverni ishga tushirishda xatolik: " + ex.Message, "PACS Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void CheckServerHealth()
        {
            bool online = IsPortOpen("127.0.0.1", SERVER_PORT, 400);
            if (!online)
            {
                // Agar server to'xtab qolgan bo'lsa, qayta tiklaymiz
                StartServerProcess();
            }
        }

        private void RestartServer()
        {
            StopServerProcess();
            Thread.Sleep(1000);
            StartServerProcess();
            trayIcon.ShowBalloonTip(2000, "Sabadarmon PACS", "Server qayta ishga tushirildi.", ToolTipIcon.Info);
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

            // run_server.py ni ishlatayotgan boshqa python jarayonlarini ham xavfsiz to'xtatamiz
            try
            {
                string scriptPath = Path.Combine(baseDir, "run_server.py");
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

        private bool IsPortOpen(string host, int port, int timeoutMs)
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    var result = client.BeginConnect(host, port, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(timeoutMs);
                    if (!success) return false;
                    client.EndConnect(result);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        private string FindPython(string baseDir)
        {
            string localPythonw = Path.Combine(baseDir, "python", "pythonw.exe");
            if (File.Exists(localPythonw)) return localPythonw;

            string py311w = @"C:\Python311\pythonw.exe";
            if (File.Exists(py311w)) return py311w;

            string py311 = @"C:\Python311\python.exe";
            if (File.Exists(py311)) return py311;

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string userPyw = Path.Combine(localAppData, @"Programs\Python\Python311\pythonw.exe");
            if (File.Exists(userPyw)) return userPyw;

            return "pythonw.exe";
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
