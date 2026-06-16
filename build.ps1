param(
    [switch]$NoCache,
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [int]$Percent,
        [string]$Title,
        [string]$Detail = ""
    )
    Write-Host ""
    Write-Host ("[{0,3}%] {1}" -f $Percent, $Title) -ForegroundColor Cyan
    if ($Detail) {
        Write-Host "      $Detail" -ForegroundColor DarkGray
    }
}

function Write-Ok {
    param([string]$Message)
    Write-Host "      OK: $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "      WARN: $Message" -ForegroundColor Yellow
}

function Run {
    param(
        [string]$Command,
        [string[]]$Arguments
    )
    Write-Host "      > $Command $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
}

$started = Get-Date

Write-Host "WhatsApp AI Memory Bot - Docker Build" -ForegroundColor White
Write-Host "Mode log: detail/plain, cocok untuk melihat proses build di terminal." -ForegroundColor DarkGray

Write-Step 5 "Cek Docker"
Run "docker" @("version")
Run "docker" @("compose", "version")
Write-Ok "Docker dan Docker Compose tersedia."

Write-Step 15 "Cek file environment"
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Warn ".env belum ada, dibuat dari .env.example. Ganti secret sebelum production."
    } else {
        throw ".env dan .env.example tidak ditemukan."
    }
} else {
    Write-Ok ".env ditemukan."
}

Write-Step 25 "Validasi docker-compose.yml"
Run "docker" @("compose", "config")
Write-Ok "Konfigurasi Compose valid."

Write-Step 40 "Build image Docker" "Log layer Docker ditampilkan lengkap."
$buildArgs = @("compose", "build", "--progress=plain")
if ($NoCache) {
    $buildArgs += "--no-cache"
}
Run "docker" $buildArgs
Write-Ok "Build image selesai."

if (-not $SkipStart) {
    Write-Step 75 "Start container"
    Run "docker" @("compose", "up", "-d")
    Write-Ok "Container dijalankan."

    Write-Step 88 "Tampilkan status container"
    Run "docker" @("compose", "ps")

    Write-Step 95 "Log awal aplikasi" "Menampilkan 80 baris log terakhir."
    Run "docker" @("compose", "logs", "--tail=80")
} else {
    Write-Step 95 "Skip start container"
    Write-Warn "Build selesai, container tidak dijalankan karena parameter -SkipStart."
}

$elapsed = New-TimeSpan -Start $started -End (Get-Date)
Write-Step 100 "Selesai"
Write-Host ("      Durasi: {0:mm\:ss}" -f $elapsed) -ForegroundColor Green
Write-Host "      Dashboard: http://localhost:5000" -ForegroundColor Green
Write-Host "      Jika port host diubah, pakai http://IP_SERVER:PORT" -ForegroundColor Green
