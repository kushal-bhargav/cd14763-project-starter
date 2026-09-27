# ==============================================================================
# AWS Udacity Project 2 - Customer Support AI Agent
# CLI Evidence Capture Script - Tests 1-6
#
# PURPOSE:
#   Runs all 6 functional tests against the deployed AgentCore runtime,
#   captures terminal screenshots automatically, and saves both .png and .txt
#   evidence files to:  starter/evidence/
#
# USAGE:
#   1. Open PowerShell and activate your venv314 environment
#   2. Zoom out your terminal (Ctrl+-) and maximize the window
#   3. Update AWS credentials in the section below if needed
#   4. Run:
#        cd "C:\Users\KushalBhargav\OneDrive - Systech Solutions, Inc\udacity\project_2\cd14763-project-starter"
#        .\testing_script_cli_evidence\run_tests.ps1
#
# OUTPUT:
#   starter\evidence\01-order-tracking.png / .txt
#   starter\evidence\02-refund-processing.png / .txt
#   starter\evidence\03-rag.png / .txt
#   starter\evidence\04-memory-session-A.png / .txt
#   starter\evidence\04-memory-session-B.png / .txt
#   starter\evidence\05-loyalty-discount.png / .txt
#   starter\evidence\06-browser.png / .txt
#
# NOTE:
#   Test 4 (Memory) waits 35 seconds between Session A and B automatically.
#   CloudWatch alarm screenshot (07-cloudwatch-alarm.png) must be captured
#   manually from the AWS Console.
# ==============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding            = [System.Text.Encoding]::UTF8

# ------------------------------------------------------------------------------
# AWS CREDENTIALS — loaded from .env file
# ------------------------------------------------------------------------------
$scriptRoot  = "C:\Users\KushalBhargav\OneDrive - Systech Solutions, Inc\udacity\project_2\cd14763-project-starter"
$envFile = Join-Path $scriptRoot ".env"

if (Test-Path $envFile) {
    Write-Host "Loading credentials from .env..." -ForegroundColor Cyan
    Get-Content $envFile | Where-Object { $_ -match '^[A-Za-z0-9_]+=' } | ForEach-Object {
        $name, $value = $_.Split('=', 2)
        $value = $value.Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($name, $value)
    }
} else {
    Write-Host "WARNING: .env file not found at $envFile. Relying on existing environment variables." -ForegroundColor Yellow
}

$env:AGENTCORE_SUPPRESS_RECOMMENDATION = "1"

# ------------------------------------------------------------------------------
# PATHS
# Resolve all paths relative to the cd14763-project-starter root so this
# script works regardless of where PowerShell's CWD is set.
# ------------------------------------------------------------------------------
$scriptRoot  = "C:\Users\KushalBhargav\OneDrive - Systech Solutions, Inc\udacity\project_2\cd14763-project-starter"
$agentcore   = "C:\Users\KushalBhargav\OneDrive - Systech Solutions, Inc\udacity\project_2\venv314\Scripts\agentcore.exe"
$starterDir  = Join-Path $scriptRoot "starter"
$evidenceDir = Join-Path $starterDir "evidence"
$sep         = "=" * 70

# Verify critical paths exist before running
if (-not (Test-Path $agentcore)) {
    Write-Host "ERROR: agentcore not found at: $agentcore" -ForegroundColor Red
    Write-Host "       Make sure venv314 is installed correctly." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $starterDir ".bedrock_agentcore.yaml"))) {
    Write-Host "ERROR: .bedrock_agentcore.yaml not found in: $starterDir" -ForegroundColor Red
    exit 1
}

# Load Windows Forms for screenshot + SendKeys
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ------------------------------------------------------------------------------
# CLEAN: Delete all existing evidence files and start fresh
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host $sep -ForegroundColor Red
Write-Host "  CLEARING existing evidence folder..." -ForegroundColor Red
Write-Host $sep -ForegroundColor Red
if (Test-Path $evidenceDir) {
    Get-ChildItem -Path $evidenceDir | Remove-Item -Force
    Write-Host "  All previous evidence files deleted." -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Path $evidenceDir | Out-Null
    Write-Host "  Evidence folder created fresh." -ForegroundColor Yellow
}
Write-Host ""
Start-Sleep -Seconds 1

# ------------------------------------------------------------------------------
# SCREENSHOT FUNCTION
# Scrolls terminal to bottom (Ctrl+End) then captures full screen
# ------------------------------------------------------------------------------
function Take-Screenshot {
    param([string]$FilePath)
    [System.Windows.Forms.SendKeys]::SendWait("^{END}")
    Start-Sleep -Milliseconds 800
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp    = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
    $g      = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
    $bmp.Save($FilePath, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose()
    $bmp.Dispose()
    Write-Host "  >> Screenshot saved: $FilePath" -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# RUN-TEST HELPER
# ------------------------------------------------------------------------------
function Run-Test {
    param(
        [string]$Label,
        [string]$Payload,
        [string]$TxtFile,
        [string]$PngFile
    )
    Write-Host ""
    Write-Host $sep -ForegroundColor Cyan
    Write-Host "  $Label" -ForegroundColor Cyan
    Write-Host $sep -ForegroundColor Cyan
    Write-Host "  Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  agentcore invoke '$Payload'" -ForegroundColor Yellow
    Write-Host ""

    # agentcore must run from starter dir where .bedrock_agentcore.yaml lives
    Push-Location $starterDir
    $result = & $agentcore invoke $Payload 2>&1
    Pop-Location

    $result | ForEach-Object { Write-Host $_ }
    Write-Host ""

    # Save txt evidence
    $ts     = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $header = "=== $Label ===" + [Environment]::NewLine +
              "Timestamp : $ts" + [Environment]::NewLine +
              "Command   : agentcore invoke '$Payload'" + [Environment]::NewLine +
              "--- RESPONSE ---" + [Environment]::NewLine
    ($header + ($result | Out-String)) | Out-File -FilePath $TxtFile -Encoding utf8
    Write-Host "  >> Text saved  : $TxtFile" -ForegroundColor Green

    Take-Screenshot -FilePath $PngFile
}

# ==============================================================================
# TEST 1 - ORDER TRACKING
# ==============================================================================
Run-Test `
    -Label   "TEST 1 - ORDER TRACKING" `
    -Payload '{"prompt":"What is the status of order ORD-001?","customer_id":"CUST-123","session_id":"t1"}' `
    -TxtFile (Join-Path $evidenceDir "01-order-tracking.txt") `
    -PngFile (Join-Path $evidenceDir "01-order-tracking.png")

Read-Host "  [PAUSED] Verify Test 1, then press ENTER to continue"

# ==============================================================================
# TEST 2 - REFUND PROCESSING
# ==============================================================================
Run-Test `
    -Label   "TEST 2 - REFUND PROCESSING" `
    -Payload '{"prompt":"I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.","customer_id":"CUST-123","session_id":"t2"}' `
    -TxtFile (Join-Path $evidenceDir "02-refund-processing.txt") `
    -PngFile (Join-Path $evidenceDir "02-refund-processing.png")

Read-Host "  [PAUSED] Verify Test 2, then press ENTER to continue"

# ==============================================================================
# TEST 3 - KNOWLEDGE BASE / RAG
# ==============================================================================
Run-Test `
    -Label   "TEST 3 - KNOWLEDGE BASE RAG" `
    -Payload '{"prompt":"What are the benefits of the Platinum loyalty tier?","customer_id":"CUST-123","session_id":"t3"}' `
    -TxtFile (Join-Path $evidenceDir "03-rag.txt") `
    -PngFile (Join-Path $evidenceDir "03-rag.png")

Read-Host "  [PAUSED] Verify Test 3, then press ENTER to continue"

# ==============================================================================
# TEST 4A - MEMORY SESSION A
# ==============================================================================
Run-Test `
    -Label   "TEST 4A - MEMORY SESSION A" `
    -Payload '{"prompt":"Hi, I am Jane. I prefer concise responses.","customer_id":"CUST-123","session_id":"s-A"}' `
    -TxtFile (Join-Path $evidenceDir "04-memory-session-A.txt") `
    -PngFile (Join-Path $evidenceDir "04-memory-session-A.png")

Write-Host ""
Write-Host "  [WAITING 35 seconds for memory to persist before Session B...]" -ForegroundColor Magenta
for ($i = 35; $i -ge 1; $i--) {
    Write-Host "  $i seconds remaining..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 1
}

# ==============================================================================
# TEST 4B - MEMORY SESSION B
# ==============================================================================
Run-Test `
    -Label   "TEST 4B - MEMORY SESSION B" `
    -Payload '{"prompt":"Do you remember my name and communication preference?","customer_id":"CUST-123","session_id":"s-B"}' `
    -TxtFile (Join-Path $evidenceDir "04-memory-session-B.txt") `
    -PngFile (Join-Path $evidenceDir "04-memory-session-B.png")

Read-Host "  [PAUSED] Verify Test 4B memory recall, then press ENTER to continue"

# ==============================================================================
# TEST 5 - LOYALTY DISCOUNT CALCULATION
# ==============================================================================
Run-Test `
    -Label   "TEST 5 - LOYALTY DISCOUNT CALCULATION" `
    -Payload '{"prompt":"I am a Gold member with 4250 points. Calculate my discount on a 150 dollar standard order.","customer_id":"CUST-123","session_id":"t5"}' `
    -TxtFile (Join-Path $evidenceDir "05-loyalty-discount.txt") `
    -PngFile (Join-Path $evidenceDir "05-loyalty-discount.png")

Read-Host "  [PAUSED] Verify Test 5, then press ENTER to continue"

# ==============================================================================
# TEST 6 - BROWSER TOOL
# ==============================================================================
Run-Test `
    -Label   "TEST 6 - BROWSER TOOL" `
    -Payload '{"prompt":"Go to https://www.amazon.com and tell me the page title.","customer_id":"CUST-123","session_id":"t6"}' `
    -TxtFile (Join-Path $evidenceDir "06-browser.txt") `
    -PngFile (Join-Path $evidenceDir "06-browser.png")

# ==============================================================================
# FINAL SUMMARY
# ==============================================================================
Write-Host ""
Write-Host $sep -ForegroundColor Cyan
Write-Host "  ALL 6 TESTS COMPLETE - Evidence files saved:" -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Cyan
Get-ChildItem -Path $evidenceDir | ForEach-Object {
    Write-Host "  $($_.Name)" -ForegroundColor White
}
Write-Host ""
Write-Host "  NEXT: AWS Console -> CloudWatch -> capture alarm screenshot" -ForegroundColor Yellow
Write-Host "  Save as: starter\evidence\07-cloudwatch-alarm.png" -ForegroundColor Yellow
Write-Host $sep -ForegroundColor Cyan
