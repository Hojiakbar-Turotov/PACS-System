using System;
using System.IO;
using System.Diagnostics;
using System.Net.Sockets;
using System.Threading;
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

        [STAThread]
        static void Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string exePath = Application.ExecutablePath;

            bool isBackground = false;
            bool doUnregister = false;

            foreach (string arg in args)
            {
                if (arg.Equals("--background", StringComparison.OrdinalIgnoreCase) || arg.Equals("-b", StringComparison.OrdinalIgnoreCase))
                {
                    isBackground = true;
                }
                if (arg.Equals("--unregister", StringComparison.OrdinalIgnoreCase))
                {
                    doUnregister = true;
                }
            }

            if (doUnregister)
            {
                UnregisterStartup();
                MessageBox.Show("Sabadarmon PACS avtomatik ishga tushirishdan olib tashlandi.", "PACS Sozlamasi", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            // 1. Windows avtomatik yuklanishiga qo'shish (Auto-start on Windows boot)
            RegisterStartup(exePath);

            // 2. Server ishlayotganini tekshirish
            bool isRunning = IsPortOpen("127.0.0.1", SERVER_PORT, 500);

            if (!isRunning)
            {
                // Serverni orqa fonda (yashirin) ishga tushirish
                string pythonPath = FindPython(baseDir);
                string scriptPath = Path.Combine(baseDir, "run_server.py");

                if (!File.Exists(scriptPath))
                {
                    MessageBox.Show("run_server.py fayli topilmadi: " + scriptPath, "Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                if (string.IsNullOrEmpty(pythonPath) || !File.Exists(pythonPath))
                {
                    MessageBox.Show("Python (pythonw.exe) topilmadi! Iltimos, Python 3.11 o'rnatilganligini tekshiring.", "Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
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

                    Process.Start(psi);

                    // Server porti ochilishini 3 soniyagacha kutish
                    for (int i = 0; i < 15; i++)
                    {
                        Thread.Sleep(200);
                        if (IsPortOpen("127.0.0.1", SERVER_PORT, 300))
                        {
                            break;
                        }
                    }
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Serverni ishga tushirishda xatolik: " + ex.Message, "Xatolik", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
            }

            // 3. Agar foydalanuvchi qo'lda ochgan bo'lsa (birinchi marta yoki keyin), brauzerni ochish
            if (!isBackground)
            {
                try
                {
                    Process.Start(new ProcessStartInfo(SERVER_URL) { UseShellExecute = true });
                }
                catch (Exception)
                {
                    Process.Start("explorer.exe", SERVER_URL);
                }
            }
        }

        private static bool IsPortOpen(string host, int port, int timeoutMs)
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

        private static string FindPython(string baseDir)
        {
            // 1. Portativ yoki mahalliy papka
            string localPythonw = Path.Combine(baseDir, "python", "pythonw.exe");
            if (File.Exists(localPythonw)) return localPythonw;

            // 2. Tizimdagi C:\Python311\pythonw.exe
            string py311w = @"C:\Python311\pythonw.exe";
            if (File.Exists(py311w)) return py311w;

            string py311 = @"C:\Python311\python.exe";
            if (File.Exists(py311)) return py311;

            // 3. User AppData
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string userPyw = Path.Combine(localAppData, @"Programs\Python\Python311\pythonw.exe");
            if (File.Exists(userPyw)) return userPyw;

            // 4. Standart PATH dan qidirish
            string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
            string[] dirs = pathEnv.Split(';');
            foreach (string dir in dirs)
            {
                try
                {
                    string target = Path.Combine(dir.Trim(), "pythonw.exe");
                    if (File.Exists(target)) return target;
                }
                catch { }
            }

            return "pythonw.exe";
        }

        private static void RegisterStartup(string exePath)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RUN_KEY, true))
                {
                    if (key != null)
                    {
                        string val = "\"" + exePath + "\" --background";
                        key.SetValue(APP_NAME, val);
                    }
                }
            }
            catch { }
        }

        private static void UnregisterStartup()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RUN_KEY, true))
                {
                    if (key != null)
                    {
                        key.DeleteValue(APP_NAME, false);
                    }
                }
            }
            catch { }
        }
    }
}
