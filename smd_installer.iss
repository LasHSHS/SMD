; Snapchat Memories Downloader - Inno Setup Script
; Creates a professional Windows installer

[Setup]
AppName=Snapchat Memories Downloader
AppVersion=2.1
AppPublisher=Snapchat Memories Team
AppPublisherURL=https://github.com
DefaultDirName={autopf}\Snapchat Memories Downloader
DefaultGroupName=Snapchat Memories Downloader
OutputDir=installer_output
OutputBaseFilename=Snapchat-Memories-Downloader-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
AllowNoIcons=yes
ShowLanguageDialog=no
LicenseFile=README.md
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\smd.exe
DisableWelcomePage=no

; Modern UI settings - using built-in defaults

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Main executable and all its dependencies from dist\smd folder
Source: "dist\smd\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Copy icon separately for shortcuts
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Create Start Menu shortcuts
Name: "{group}\Snapchat Memories Downloader"; Filename: "{app}\smd.exe"; IconFilename: "{app}\icon.ico"; Comment: "Download your Snapchat memories"; WorkingDir: "{app}"
Name: "{group}\Uninstall Snapchat Memories Downloader"; Filename: "{uninstallexe}"
; Optional: Create desktop shortcut
Name: "{userdesktop}\Snapchat Memories Downloader"; Filename: "{app}\smd.exe"; IconFilename: "{app}\icon.ico"; Comment: "Download your Snapchat memories"; WorkingDir: "{app}"

[Run]
; Ask user if they want to launch the app after installation
Filename: "{app}\smd.exe"; Description: "Launch Snapchat Memories Downloader"; Flags: nowait postinstall skipifsilent unchecked; WorkingDir: "{app}"

[InstallDelete]
; Clean up old versions
Type: filesandordirs; Name: "{app}\*"

[Code]
// Check if .NET is installed (optional - remove if not needed)
function IsNetInstalledAndNew(): Boolean;
var
  Version: string;
begin
  Result := True; // For now, assume it's fine - Python 3.12 is self-contained
end;

// Custom wizard page to show post-install info
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    MsgBox('Snapchat Memories Downloader has been installed successfully!' + #13#13 +
           'Everything is included — no Python, ffmpeg, or other tools to install.' + #13#13 +
           'Click Finish, then open SMD from the Start Menu.' + #13#13 +
           'For support, visit: https://github.com',
           mbInformation, MB_OK);
end;
