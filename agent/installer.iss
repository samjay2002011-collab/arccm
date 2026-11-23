; Script generated for CMSync Windows Installer — Clean Upgrade Engine
#define MyAppName "CMSync Client"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "CMSync Team"
#define MyAppURL "https://arccm.fastapicloud.dev"
#define MyAppExeName "CMSync.exe"

[Setup]
AppId={{CMSync-Client-Official-AppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\CMSync
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
UsedUserAreasWarning=no
OutputDir=dist_installer
OutputBaseFilename=CMSync_Setup
SetupIconFile=cmsync.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Start automatically with Windows"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\CMSync.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "cmsync.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\cmsync.ico"
Name: "{autoprograms}\{#MyAppName}\Uninstall CMSync"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\cmsync.ico"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CMSync"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startupicon; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM CMSync.exe"; Flags: runhidden; RunOnceId: "KillCMSyncOnUninstall"

[Code]
procedure KillCMSync();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM CMSync.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
end;

procedure CleanUninstallEntries(RootKey: Integer; const BaseKey: String);
var
  SubKeys: TArrayOfString;
  I: Integer;
  SubKeyPath: String;
  DisplayName, UninstallStr, QuietUninstallStr, InstallLoc: String;
  TargetKeyName, UninstCmd: String;
  ResultCode: Integer;
begin
  if not RegGetSubkeyNames(RootKey, BaseKey, SubKeys) then
    Exit;

  for I := 0 to GetArrayLength(SubKeys) - 1 do
  begin
    TargetKeyName := SubKeys[I];
    // Keep our own AppId intact so Inno Setup can manage it
    if (CompareText(TargetKeyName, '{CMSync-Client-Official-AppId}_is1') = 0) or
       (CompareText(TargetKeyName, '{{CMSync-Client-Official-AppId}}_is1') = 0) or
       (CompareText(TargetKeyName, 'CMSync-Client-Official-AppId') = 0) then
      Continue;

    SubKeyPath := BaseKey + '\' + TargetKeyName;
    DisplayName := '';
    UninstallStr := '';
    QuietUninstallStr := '';
    InstallLoc := '';

    RegQueryStringValue(RootKey, SubKeyPath, 'DisplayName', DisplayName);
    RegQueryStringValue(RootKey, SubKeyPath, 'UninstallString', UninstallStr);
    RegQueryStringValue(RootKey, SubKeyPath, 'QuietUninstallString', QuietUninstallStr);
    RegQueryStringValue(RootKey, SubKeyPath, 'InstallLocation', InstallLoc);

    if (Pos('CMSYNC', Uppercase(TargetKeyName)) > 0) or
       (Pos('CMSYNC', Uppercase(DisplayName)) > 0) or
       (Pos('CMSYNC', Uppercase(UninstallStr)) > 0) or
       (Pos('CMSYNC', Uppercase(InstallLoc)) > 0) then
    begin
      UninstCmd := '';
      if QuietUninstallStr <> '' then
        UninstCmd := RemoveQuotes(QuietUninstallStr)
      else if UninstallStr <> '' then
        UninstCmd := RemoveQuotes(UninstallStr);

      if (UninstCmd <> '') and FileExists(UninstCmd) then
      begin
        Exec(UninstCmd, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SILENT /S', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Sleep(1200);
      end;

      // Clean up orphaned or remaining registry key
      RegDeleteKeyIncludingSubkeys(RootKey, SubKeyPath);
    end;
  end;
end;

procedure CleanStartupRunValues(RootKey: Integer; const SubKeyPath: String);
var
  ValNames: TArrayOfString;
  I: Integer;
  ValData: String;
begin
  if RegGetValueNames(RootKey, SubKeyPath, ValNames) then
  begin
    for I := 0 to GetArrayLength(ValNames) - 1 do
    begin
      ValData := '';
      RegQueryStringValue(RootKey, SubKeyPath, ValNames[I], ValData);
      if (Pos('CMSYNC', Uppercase(ValNames[I])) > 0) or (Pos('CMSYNC', Uppercase(ValData)) > 0) then
      begin
        RegDeleteValue(RootKey, SubKeyPath, ValNames[I]);
      end;
    end;
  end;
end;

procedure CleanStartupApprovedValues(RootKey: Integer; const SubKeyPath: String);
var
  ValNames: TArrayOfString;
  I: Integer;
begin
  if RegGetValueNames(RootKey, SubKeyPath, ValNames) then
  begin
    for I := 0 to GetArrayLength(ValNames) - 1 do
    begin
      if Pos('CMSYNC', Uppercase(ValNames[I])) > 0 then
      begin
        RegDeleteValue(RootKey, SubKeyPath, ValNames[I]);
      end;
    end;
  end;
end;

procedure CleanShortcutsInDir(const DirPath: String);
var
  FindRec: TFindRec;
begin
  if DirExists(DirPath) then
  begin
    if FindFirst(DirPath + '\*CMSync*.*', FindRec) then
    begin
      try
        repeat
          DeleteFile(DirPath + '\' + FindRec.Name);
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;
  end;
end;

procedure PerformCleanUpgrade();
begin
  // 1. Terminate any running CMSync processes
  KillCMSync();

  // 2. Remove all old CMSync installations from Control Panel
  CleanUninstallEntries(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall');
  CleanUninstallEntries(HKEY_LOCAL_MACHINE, 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall');
  CleanUninstallEntries(HKEY_CURRENT_USER, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall');

  // 3. Clean startup run entries
  CleanStartupRunValues(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run');
  CleanStartupRunValues(HKEY_LOCAL_MACHINE, 'Software\Microsoft\Windows\CurrentVersion\Run');
  CleanStartupRunValues(HKEY_LOCAL_MACHINE, 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run');
  CleanStartupRunValues(HKEY_LOCAL_MACHINE, 'Software\WOW6432Node\Software\Microsoft\Windows\CurrentVersion\Run');

  // 4. Clean StartupApproved keys
  CleanStartupApprovedValues(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run');
  CleanStartupApprovedValues(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder');
  CleanStartupApprovedValues(HKEY_LOCAL_MACHINE, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run');
  CleanStartupApprovedValues(HKEY_LOCAL_MACHINE, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder');

  // 5. Clean Startup and Desktop shortcut files
  CleanShortcutsInDir(ExpandConstant('{userstartup}'));
  CleanShortcutsInDir(ExpandConstant('{commonstartup}'));
  CleanShortcutsInDir(ExpandConstant('{autodesktop}'));
  CleanShortcutsInDir(ExpandConstant('{userdesktop}'));
  CleanShortcutsInDir(ExpandConstant('{commondesktop}'));
end;

function InitializeSetup(): Boolean;
begin
  PerformCleanUpgrade();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldDir1, OldDir2, OldDir3: String;
begin
  if CurStep = ssInstall then
  begin
    KillCMSync();

    OldDir1 := ExpandConstant('{pf32}\CMSync');
    OldDir2 := ExpandConstant('{pf64}\CMSync');
    OldDir3 := ExpandConstant('{localappdata}\CMSync');

    // Clean old binary install directories while never touching %APPDATA%\CMSync
    if DirExists(OldDir1) and (CompareText(OldDir1, ExpandConstant('{app}')) <> 0) then
      DelTree(OldDir1, True, True, True);
    if DirExists(OldDir2) and (CompareText(OldDir2, ExpandConstant('{app}')) <> 0) then
      DelTree(OldDir2, True, True, True);
    if DirExists(OldDir3) and (CompareText(OldDir3, ExpandConstant('{app}')) <> 0) then
      DelTree(OldDir3, True, True, True);
  end;
end;
