; Installateur Desky (CDC §15).
;
; Trois exigences du cahier des charges, et chacune a sa raison :
;
;   * portée **utilisateur**, donc aucune élévation UAC. Un animal de compagnie
;     de bureau qui demande les droits administrateur pour s'installer perd la
;     moitié de ses candidats sur cet écran ;
;   * option de lancement au démarrage **décochée par défaut**. Le §12 interdit
;     les comportements imposés, et s'inviter au démarrage sans le demander en
;     est un ;
;   * icône fournie, celle que `tools/make_icon.py` rend depuis le moteur.
;
; L'installateur ne crée pas la clé de démarrage lui-même : il coche l'option
; du produit, qui écrit `HKCU\...\Run` par son propre chemin (cf. `win32.
; set_autostart`). Deux écritures concurrentes de la même clé finiraient par
; diverger, et c'est le panneau de réglages qui doit rester la référence.
;
; Compilation :
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\desky.iss

#define AppName "Desky"
#define AppExe "Desky.exe"
#define AppPublisher "Desky"
; Passée par `tools/build.py` (`/DAppVersion=`), qui la lit dans
; `pet/__init__.py`. La valeur ci-dessous n'est qu'un repli pour une
; compilation manuelle : deux numéros de version finissent toujours par
; diverger, et celui-ci est le seul que l'utilisateur verra.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7F3C9A6E-2B41-4E8D-9C15-DE5A7B0C4F32}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Desky-{#AppVersion}-setup
SetupIconFile=desky.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; **Aucune élévation.** `lowest` installe dans le profil de l'utilisateur, ce
; qui rend `{autopf}` équivalent à `{localappdata}\Programs`.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Desky ne tourne que sur Windows 10 et 11, et en 64 bits : le §1 le pose, et
; l'awareness DPI per-monitor-v2 dont dépend tout le placement n'existe pas
; avant la 1703.
MinVersion=10.0.15063
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Décochée par défaut, comme le §15 l'exige.
Name: "autostart"; Description: "Lancer Desky au démarrage de Windows"; Flags: unchecked

[Files]
Source: "..\dist\Desky\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Portée utilisateur exclusivement : jamais HKLM, qui demanderait l'élévation
; et inscrirait pour tous les comptes de la machine.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Les données vivent dans %LOCALAPPDATA%\Desky. Elles ne sont **pas** effacées
; à la désinstallation : réinstaller doit retrouver son robot, son nom et son
; inventaire. La purge existe, elle est dans les réglages du produit, et c'est
; un geste délibéré de l'utilisateur — pas un effet de bord.
Type: dirifempty; Name: "{app}"
