Function KuractusRequireProcessClosed
  ; PowerShell is used as a read-only process check because Tauri's NSIS
  ; process plugin is loaded after custom preinstall hooks are included.
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -Command "if (Get-Process -Name aura-desktop,kuractus-desktop -ErrorAction SilentlyContinue) { exit 23 }"' $R0
  ${If} $R0 != 0
    IfSilent kuractus_process_check_silent
    MessageBox MB_OK|MB_ICONSTOP "Kuractus may be running or its process state could not be verified. Close Kuractus yourself, then run this installer again."
    Abort
    kuractus_process_check_silent:
      SetErrorLevel 2
      Abort
  ${EndIf}
FunctionEnd

!macro NSIS_HOOK_PREINSTALL
  ; Stop safely before Tauri's default install check can terminate the current
  ; executable in silent mode. The check covers the previous AURA binary too.
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
