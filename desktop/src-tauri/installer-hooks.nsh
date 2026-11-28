Function KuractusRequireProcessClosed
  nsis_tauri_utils::FindProcessCurrentUser "$R1"
  Pop $R0
  ${If} $R0 = 0
    IfSilent kuractus_process_running_silent
    MessageBox MB_OK|MB_ICONSTOP "Kuractus is running. Close it, then run this installer again."
    Abort
    kuractus_process_running_silent:
      SetErrorLevel 2
      Abort
  ${EndIf}
FunctionEnd

!macro NSIS_HOOK_PREINSTALL
  ; Tauri's default install check terminates the current executable in silent
  ; mode. Guard both this release and the previous AURA binary so upgrades
  ; stop safely instead of interrupting a running desktop session.
  StrCpy $R1 "aura-desktop.exe"
  Call KuractusRequireProcessClosed
  StrCpy $R1 "kuractus-desktop.exe"
  Call KuractusRequireProcessClosed
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; The new Kuractus shortcuts are created by Tauri. Remove only stale
  ; AURA-named shortcuts left by older installs; never touch the data folder.
  Delete "$SMPROGRAMS\AURA.lnk"
  Delete "$DESKTOP\AURA.lnk"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "Kuractus"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  Delete "$SMPROGRAMS\Kuractus.lnk"
  Delete "$DESKTOP\Kuractus.lnk"
!macroend
