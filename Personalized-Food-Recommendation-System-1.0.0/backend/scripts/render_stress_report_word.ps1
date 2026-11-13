param(
    [Parameter(Mandatory = $true)][string]$DocumentPath,
    [Parameter(Mandatory = $true)][string]$PdfPath
)
$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $confirmConversions = $false
    $readOnly = $true
    $addToRecentFiles = $false
    $saveChanges = 0
    $document = $word.Documents.Open([ref]$DocumentPath, [ref]$confirmConversions, [ref]$readOnly, [ref]$addToRecentFiles)
    $document.Repaginate()
    $document.ExportAsFixedFormat($PdfPath, 17)
} finally {
    if ($null -ne $document) {
        $document.Close([ref]$saveChanges)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
    if ($null -ne $word) {
        $word.Quit([ref]$saveChanges)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
}
