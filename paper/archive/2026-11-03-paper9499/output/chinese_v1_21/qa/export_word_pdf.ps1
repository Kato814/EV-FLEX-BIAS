param([Parameter(Mandatory=$true)][string]$DocInput,[Parameter(Mandatory=$true)][string]$PdfOutput)
$ErrorActionPreference = 'Stop'
$wordInstance = $null
$wordDocument = $null
try {
    $wordInstance = New-Object -ComObject Word.Application
    $wordInstance.Visible = $false
    $wordInstance.DisplayAlerts = 0
    $wordDocument = $wordInstance.Documents.Open($DocInput, $false, $true, $false)
    $wordDocument.Repaginate()
    $wordDocument.ExportAsFixedFormat($PdfOutput, 17, $false, 0, 0, 1, 1, 0, $true, $true, 0, $true, $true, $true)
    Write-Output ('Exported {0} pages' -f $wordDocument.ComputeStatistics(2))
} finally {
    $discardChanges = 0
    if ($null -ne $wordDocument) { $wordDocument.Close([ref]$discardChanges); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDocument) }
    if ($null -ne $wordInstance) { $wordInstance.Quit([ref]$discardChanges); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordInstance) }
}
