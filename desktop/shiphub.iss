; shiphub for Windows - per-user installer (no admin rights). build.py compiles it with:
;   iscc /DAppVersion=1.0.0 /DSourceDir=<dist\shiphub> /DOutputDir=<dist> /DIconFile=<build\shiphub.ico> shiphub.iss
; Installs to %LOCALAPPDATA%\Programs\shiphub, adds shiphub to the Start menu (and optionally the desktop) and lists it
; in Settings > Apps. The window keeps its data (what you saved in it) in %LOCALAPPDATA%\shiphub, which
; uninstalling leaves in place so a reinstall finds it again.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\shiphub"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef IconFile
  #define IconFile "build\shiphub.ico"
#endif

[Setup]
AppId={{E81247BA-698B-569E-A6DE-E1E1C366EEFB}
AppName=shiphub
AppVersion={#AppVersion}
AppVerName=shiphub {#AppVersion}
AppPublisher=Juwen Lie
AppPublisherURL=https://juw12.github.io/shiphub/
AppSupportURL=https://github.com/juw12/shiphub
DefaultDirName={autopf}\shiphub
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=shiphub-Windows-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\shiphub.exe
UninstallDisplayName=shiphub
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\shiphub"; Filename: "{app}\shiphub.exe"; Comment: "Pinterest for app ideas, with forum threads"
Name: "{userdesktop}\shiphub"; Filename: "{app}\shiphub.exe"; Comment: "Pinterest for app ideas, with forum threads"; Tasks: desktopicon

[Run]
Filename: "{app}\shiphub.exe"; Description: "{cm:LaunchProgram,shiphub}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\shiphub.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "Stopshiphub"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  { Updating: close an open shiphub window first so its files can be replaced. }
  if FileExists(ExpandConstant('{app}\shiphub.exe')) then
    Exec(ExpandConstant('{app}\shiphub.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
