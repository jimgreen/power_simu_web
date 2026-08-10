param(
    [Parameter(Mandatory = $true)]
    [string]$InputDocx,

    [Parameter(Mandatory = $true)]
    [string]$OutputPdf
)

$ErrorActionPreference = 'Stop'

$word = $null
$document = $null

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0

    $document = $word.Documents.Open($InputDocx, $false, $true)
    $document.ExportAsFixedFormat(
        $OutputPdf,
        17,
        $false,
        0,
        0,
        1,
        9999,
        0,
        $true,
        $true,
        0,
        $true,
        $true,
        $false
    )
    $document.Close(0)
    $document = $null
    $word.Quit()
    $word = $null

    Get-Item -LiteralPath $OutputPdf | Select-Object FullName, Length, LastWriteTime
}
finally {
    if ($null -ne $document) {
        try { $document.Close(0) } catch {}
    }
    if ($null -ne $word) {
        try { $word.Quit() } catch {}
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
