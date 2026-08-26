[CmdletBinding()]
param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"),
  [string]$SecretArnsPath = (Join-Path $PSScriptRoot "secret-arns.json"),
  [string]$ImageTag = "",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Require-Command {
  param([string]$Name)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $Name"
  }
}

function Invoke-Native {
  param(
    [string]$Command,
    [string[]]$Arguments
  )

  $output = & $Command @Arguments 2>&1
  if ($LASTEXITCODE -ne 0) {
    $details = ($output | Out-String).Trim()
    throw "$Command failed ($LASTEXITCODE): $details"
  }
  return $output
}

function Invoke-Aws {
  param([string[]]$Arguments)
  return Invoke-Native -Command "aws" -Arguments $Arguments
}

function Invoke-AwsJson {
  param([string[]]$Arguments)
  $raw = Invoke-Aws -Arguments $Arguments
  $text = ($raw | Out-String).Trim()
  if (-not $text) {
    throw "AWS returned no JSON for: aws $($Arguments -join ' ')"
  }
  return $text | ConvertFrom-Json
}

function Get-RequiredProperty {
  param(
    [object]$Object,
    [string]$Name
  )

  $property = $Object.PSObject.Properties[$Name]
  if ($null -eq $property -or $null -eq $property.Value) {
    throw "Missing required configuration property: $Name"
  }
  return $property.Value
}

function Assert-RealValue {
  param(
    [string]$Name,
    [object]$Value
  )

  $text = [string]$Value
  if ([string]::IsNullOrWhiteSpace($text)) {
    throw "$Name cannot be empty"
  }

  $badMarkers = @(
    "REPLACE_WITH",
    "ACCOUNT_ID",
    "example.com",
    "xxxxx",
    "your-",
    "<",
    ">"
  )
  foreach ($marker in $badMarkers) {
    if ($text.Contains($marker, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "$Name still contains placeholder text: $text"
    }
  }
}

function Get-DesiredCount {
  param(
    [object]$Config,
    [string]$Name
  )

  $value = Get-RequiredProperty -Object $Config.desiredCounts -Name $Name
  $number = [int]$value
  if ($number -lt 1) {
    throw "desiredCounts.$Name must be at least 1"
  }
  return $number
}

function Get-TaskSize {
  param(
    [object]$Config,
    [string]$Name,
    [string]$Property,
    [int]$Fallback
  )

  $sizing = $Config.PSObject.Properties["taskSizing"]
  if ($null -eq $sizing -or $null -eq $sizing.Value) {
    return $Fallback
  }

  $service = $sizing.Value.PSObject.Properties[$Name]
  if ($null -eq $service -or $null -eq $service.Value) {
    return $Fallback
  }

  $value = $service.Value.PSObject.Properties[$Property]
  if ($null -eq $value -or $null -eq $value.Value) {
    return $Fallback
  }
  return [int]$value.Value
}

function Get-SecretEntries {
  param([object]$SecretMap)

  $entries = @()
  foreach ($property in $SecretMap.PSObject.Properties) {
    Assert-RealValue -Name "secretArns.$($property.Name)" -Value $property.Value
    $entries += [ordered]@{
      name = $property.Name
      valueFrom = [string]$property.Value
    }
  }

  $required = @(
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
    "REFERRAL_HASH_SALT"
  )
  foreach ($name in $required) {
    if (-not ($entries.name -contains $name)) {
      throw "secret-arns.json is missing required secret: $name"
    }
  }
  return $entries
}

function Get-SecretEntriesForService {
  param(
    [object]$SecretMap,
    [string]$ServiceName
  )

  $core = @(
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
    "REFERRAL_HASH_SALT"
  )
  $allowed = [System.Collections.Generic.HashSet[string]]::new([string[]]$core)

  if ($ServiceName -eq "api") {
    foreach ($property in $SecretMap.PSObject.Properties) {
      $allowed.Add($property.Name) | Out-Null
    }
  }
  elseif ($ServiceName -eq "content-worker") {
    $allowed.Add("MISTRAL_API_KEY") | Out-Null
  }
  elseif ($ServiceName -eq "brand-discovery-worker") {
    $allowed.Add("DEFAULT_AGENT_API_KEY") | Out-Null
  }
  elseif ($ServiceName -in @("integration-worker", "integration-dispatcher")) {
    $allowed.Add("INTEGRATION_GOOGLE_CLIENT_SECRET") | Out-Null
    $allowed.Add("INTEGRATION_MICROSOFT_CLIENT_SECRET") | Out-Null
  }

  $entries = @()
  foreach ($property in $SecretMap.PSObject.Properties) {
    if ($allowed.Contains($property.Name)) {
      $entries += [ordered]@{
        name = $property.Name
        valueFrom = [string]$property.Value
      }
    }
  }
  return $entries
}

function New-LogConfiguration {
  param(
    [string]$GroupName,
    [string]$Region
  )

  return [ordered]@{
    logDriver = "awslogs"
    options = [ordered]@{
      "awslogs-group" = $GroupName
      "awslogs-region" = $Region
      "awslogs-stream-prefix" = "ecs"
    }
  }
}

function New-BackendTaskDefinition {
  param(
    [string]$Family,
    [string]$ContainerName,
    [string]$Image,
    [string[]]$Command,
    [int]$Cpu,
    [int]$Memory,
    [object[]]$Environment,
    [object[]]$Secrets,
    [string]$ExecutionRoleArn,
    [string]$LogGroup,
    [string]$Region,
    [int]$ContainerPort = 0,
    [string]$PortName = "",
    [string]$WorkerHealthCommand = "exit 0"
  )

  $healthCommand = 'python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(''http://127.0.0.1:8000/health'').status==200 else 1)"'
  $container = [ordered]@{
    name = $ContainerName
    image = $Image
    essential = $true
    command = $Command
    environment = $Environment
    secrets = $Secrets
    stopTimeout = 120
    linuxParameters = [ordered]@{
      initProcessEnabled = $true
    }
    logConfiguration = New-LogConfiguration -GroupName $LogGroup -Region $Region
    healthCheck = [ordered]@{
      command = @("CMD-SHELL", $WorkerHealthCommand)
      interval = 30
      timeout = 5
      retries = 3
      startPeriod = 30
    }
  }

  if ($ContainerPort -gt 0) {
    $container.portMappings = @(
      [ordered]@{
        name = $PortName
        containerPort = $ContainerPort
        hostPort = $ContainerPort
        protocol = "tcp"
      }
    )
    $container.healthCheck = [ordered]@{
      command = @("CMD-SHELL", $healthCommand)
      interval = 30
      timeout = 5
      retries = 3
      startPeriod = 30
    }
  }

  return [ordered]@{
    family = $Family
    networkMode = "awsvpc"
    requiresCompatibilities = @("FARGATE")
    cpu = [string]$Cpu
    memory = [string]$Memory
    executionRoleArn = $ExecutionRoleArn
    containerDefinitions = @($container)
  }
}

function New-FrontendTaskDefinition {
  param(
    [string]$Family,
    [string]$Image,
    [int]$Cpu,
    [int]$Memory,
    [string]$BackendOrigin,
    [string]$ExecutionRoleArn,
    [string]$LogGroup,
    [string]$Region
  )

  $healthCommand = 'node -e "fetch(''http://127.0.0.1:3000/'').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))"'
  $container = [ordered]@{
    name = "frontend"
    image = $Image
    essential = $true
    environment = @(
      [ordered]@{ name = "NODE_ENV"; value = "production" },
      [ordered]@{ name = "HOSTNAME"; value = "0.0.0.0" },
      [ordered]@{ name = "PORT"; value = "3000" },
      [ordered]@{ name = "BACKEND_ORIGIN"; value = $BackendOrigin }
    )
    portMappings = @(
      [ordered]@{
        name = "frontend"
        containerPort = 3000
        hostPort = 3000
        protocol = "tcp"
      }
    )
    stopTimeout = 120
    linuxParameters = [ordered]@{
      initProcessEnabled = $true
    }
    logConfiguration = New-LogConfiguration -GroupName $LogGroup -Region $Region
    healthCheck = [ordered]@{
      command = @("CMD-SHELL", $healthCommand)
      interval = 30
      timeout = 5
      retries = 3
      startPeriod = 30
    }
  }

  return [ordered]@{
    family = $Family
    networkMode = "awsvpc"
    requiresCompatibilities = @("FARGATE")
    cpu = [string]$Cpu
    memory = [string]$Memory
    executionRoleArn = $ExecutionRoleArn
    containerDefinitions = @($container)
  }
}

function Ensure-EcrRepository {
  param(
    [string]$RepositoryName,
    [string]$Region
  )

  $repository = $null
  try {
    $repository = Invoke-AwsJson -Arguments @("ecr", "describe-repositories", "--repository-names", $RepositoryName, "--region", $Region)
  }
  catch {
    if (-not $_.Exception.Message.Contains("RepositoryNotFoundException")) {
      throw
    }
  }

  if ($null -eq $repository) {
    Invoke-Aws -Arguments @("ecr", "create-repository", "--repository-name", $RepositoryName, "--image-tag-mutability", "IMMUTABLE", "--image-scanning-configuration", "scanOnPush=true", "--region", $Region) | Out-Null
  }
  elseif ($repository.repositories[0].imageTagMutability -ne "IMMUTABLE") {
    throw "ECR repository $RepositoryName must use IMMUTABLE image tags"
  }
}

function Ensure-LogGroup {
  param(
    [string]$Name,
    [int]$RetentionDays,
    [string]$Region,
    [string]$KmsKeyArn
  )

  try {
    Invoke-Aws -Arguments @("logs", "create-log-group", "--log-group-name", $Name, "--kms-key-id", $KmsKeyArn, "--region", $Region) | Out-Null
  }
  catch {
    if (-not $_.Exception.Message.Contains("ResourceAlreadyExists")) {
      throw
    }
  }

  $logGroup = Invoke-AwsJson -Arguments @("logs", "describe-log-groups", "--log-group-name-prefix", $Name, "--region", $Region)
  if ($logGroup.logGroups.Count -ne 1 -or $logGroup.logGroups[0].kmsKeyId -eq $null) {
    throw "CloudWatch log group $Name must be encrypted with the configured KMS key"
  }
  Invoke-Aws -Arguments @("logs", "put-retention-policy", "--log-group-name", $Name, "--retention-in-days", [string]$RetentionDays, "--region", $Region) | Out-Null
}

function Register-TaskDefinition {
  param(
    [object]$Definition,
    [string]$OutputPath,
    [string]$Region
  )

  $json = $Definition | ConvertTo-Json -Depth 20
  Set-Content -LiteralPath $OutputPath -Value $json -Encoding utf8
  $result = Invoke-AwsJson -Arguments @("ecs", "register-task-definition", "--cli-input-json", "file://$OutputPath", "--region", $Region)
  return [string]$result.taskDefinition.taskDefinitionArn
}

function Get-NetworkConfiguration {
  param(
    [object]$Config,
    [string[]]$SubnetIds
  )

  $subnets = $SubnetIds -join ","
  return "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$($Config.ecsSecurityGroupId)],assignPublicIp=DISABLED}"
}

function Ensure-Cluster {
  param(
    [string]$ClusterName,
    [string]$Region
  )

  try {
    $existing = Invoke-AwsJson -Arguments @("ecs", "describe-clusters", "--clusters", $ClusterName, "--region", $Region)
    if ($existing.clusters.Count -gt 0 -and $existing.clusters[0].status -eq "ACTIVE") {
      return
    }
  }
  catch {
  }

  Invoke-Aws -Arguments @("ecs", "create-cluster", "--cluster-name", $ClusterName, "--settings", "name=containerInsights,value=enabled", "--region", $Region) | Out-Null
}

function Validate-AwsInputs {
  param(
    [object]$Config,
    [object]$SecretMap,
    [string]$Region
  )

  $privateSubnetIds = @($Config.privateSubnetIds)
  $proxySubnetIds = @($Config.frontendProxySubnetIds)
  $overlap = @($proxySubnetIds | Where-Object { $_ -in $privateSubnetIds })
  if ($overlap.Count -gt 0) {
    throw "frontendProxySubnetIds must be dedicated and not overlap privateSubnetIds"
  }

  $allSubnetIds = @($privateSubnetIds + $proxySubnetIds)
  $subnetArguments = @("ec2", "describe-subnets", "--subnet-ids") + $allSubnetIds + @("--region", $Region)
  $subnets = Invoke-AwsJson -Arguments $subnetArguments
  if ($subnets.Subnets.Count -ne $allSubnetIds.Count) {
    throw "AWS did not return every configured private or frontend proxy subnet"
  }
  foreach ($subnet in $subnets.Subnets) {
    if ($subnet.VpcId -ne $Config.vpcId) {
      throw "Subnet $($subnet.SubnetId) is not in vpcId $($Config.vpcId)"
    }
  }

  $proxyCidrs = @(
    $subnets.Subnets |
      Where-Object { $_.SubnetId -in $proxySubnetIds } |
      ForEach-Object { [string]$_.CidrBlock } |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
      Sort-Object -Unique
  )
  if ($proxyCidrs.Count -ne $proxySubnetIds.Count) {
    throw "Every frontend proxy subnet must expose one IPv4 CIDR"
  }

  $securityGroup = Invoke-AwsJson -Arguments @("ec2", "describe-security-groups", "--group-ids", $Config.ecsSecurityGroupId, "--region", $Region)
  if ($securityGroup.SecurityGroups.Count -ne 1 -or $securityGroup.SecurityGroups[0].VpcId -ne $Config.vpcId) {
    throw "ecsSecurityGroupId does not belong to vpcId $($Config.vpcId)"
  }
  $apiIngressPermissions = @(
    $securityGroup.SecurityGroups[0].IpPermissions |
      Where-Object {
        $_.IpProtocol -eq "-1" -or (
          $_.IpProtocol -eq "tcp" -and
          [int]$_.FromPort -le 8000 -and
          [int]$_.ToPort -ge 8000
        )
      }
  )
  $apiIngressCidrs = @(
    $apiIngressPermissions |
      ForEach-Object { $_.IpRanges } |
      ForEach-Object { [string]$_.CidrIp } |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
      Sort-Object -Unique
  )
  $nonCidrApiSources = @(
    $apiIngressPermissions |
      Where-Object {
        @($_.Ipv6Ranges).Count -gt 0 -or
        @($_.PrefixListIds).Count -gt 0 -or
        @($_.UserIdGroupPairs).Count -gt 0
      }
  )
  $unexpectedApiIngress = @($apiIngressCidrs | Where-Object { $_ -notin $proxyCidrs })
  $missingApiIngress = @($proxyCidrs | Where-Object { $_ -notin $apiIngressCidrs })
  if (
    $nonCidrApiSources.Count -gt 0 -or
    $unexpectedApiIngress.Count -gt 0 -or
    $missingApiIngress.Count -gt 0
  ) {
    throw "ecsSecurityGroupId TCP 8000 ingress must exactly match frontend proxy subnet CIDRs"
  }

  $targetGroup = Invoke-AwsJson -Arguments @("elbv2", "describe-target-groups", "--target-group-arns", $Config.frontendTargetGroupArn, "--region", $Region)
  if ($targetGroup.TargetGroups.Count -ne 1) {
    throw "frontendTargetGroupArn was not found"
  }
  if ($targetGroup.TargetGroups[0].VpcId -ne $Config.vpcId -or [int]$targetGroup.TargetGroups[0].Port -ne 3000) {
    throw "frontendTargetGroupArn must belong to the configured VPC and target port 3000"
  }

  $namespaceId = ($Config.serviceConnectNamespaceArn -split "/")[-1]
  $namespace = Invoke-AwsJson -Arguments @("servicediscovery", "get-namespace", "--id", $namespaceId, "--region", $Region)
  if ($namespace.Namespace.Properties.DnsProperties.AwsCloudMapNamespaceName -eq $null -or $namespace.Namespace.Vpc -ne $Config.vpcId) {
    throw "serviceConnectNamespaceArn must be an existing private namespace in the configured VPC"
  }

  foreach ($secret in $SecretMap.PSObject.Properties) {
    Invoke-Aws -Arguments @("secretsmanager", "describe-secret", "--secret-id", [string]$secret.Value, "--region", $Region) | Out-Null
  }
  return $proxyCidrs
}

function Wait-Service {
  param(
    [string]$ClusterName,
    [string]$ServiceName,
    [string]$Region
  )

  Invoke-Aws -Arguments @("ecs", "wait", "services-stable", "--cluster", $ClusterName, "--services", $ServiceName, "--region", $Region) | Out-Null
}

function Ensure-Service {
  param(
    [string]$ClusterName,
    [string]$ServiceName,
    [string]$TaskDefinitionArn,
    [int]$DesiredCount,
    [string]$Region,
    [string]$NetworkConfiguration,
    [string]$ServiceConnectConfiguration,
    [string]$TargetGroupArn = "",
    [string]$ContainerName = "",
    [int]$ContainerPort = 0
  )

  $existing = $null
  try {
    $existing = Invoke-AwsJson -Arguments @("ecs", "describe-services", "--cluster", $ClusterName, "--services", $ServiceName, "--region", $Region)
  }
  catch {
  }

  $exists = $false
  if ($null -ne $existing -and $existing.services.Count -gt 0) {
    $exists = $existing.services[0].status -ne "INACTIVE"
  }

  if ($exists) {
    Invoke-Aws -Arguments @("ecs", "update-service", "--cluster", $ClusterName, "--service", $ServiceName, "--task-definition", $TaskDefinitionArn, "--desired-count", [string]$DesiredCount, "--network-configuration", $NetworkConfiguration, "--service-connect-configuration", $ServiceConnectConfiguration, "--deployment-configuration", "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=100", "--force-new-deployment", "--region", $Region) | Out-Null
  }
  else {
    $arguments = @("ecs", "create-service", "--cluster", $ClusterName, "--service-name", $ServiceName, "--task-definition", $TaskDefinitionArn, "--desired-count", [string]$DesiredCount, "--launch-type", "FARGATE", "--network-configuration", $NetworkConfiguration, "--service-connect-configuration", $ServiceConnectConfiguration, "--deployment-configuration", "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=100", "--region", $Region)

    if ($TargetGroupArn) {
      $arguments += @("--load-balancers", "targetGroupArn=$TargetGroupArn,containerName=$ContainerName,containerPort=$ContainerPort")
    }

    Invoke-Aws -Arguments $arguments | Out-Null
  }

  Wait-Service -ClusterName $ClusterName -ServiceName $ServiceName -Region $Region
}

function Run-Migration {
  param(
    [string]$ClusterName,
    [string]$TaskDefinitionArn,
    [string]$NetworkConfiguration,
    [string]$Region
  )

  Write-Host "Running one migration task..."
  $result = Invoke-AwsJson -Arguments @("ecs", "run-task", "--cluster", $ClusterName, "--task-definition", $TaskDefinitionArn, "--launch-type", "FARGATE", "--network-configuration", $NetworkConfiguration, "--region", $Region)

  if ($null -eq $result.tasks -or $result.tasks.Count -ne 1) {
    $failure = ($result.failures | ConvertTo-Json -Depth 10 -Compress)
    throw "ECS could not start migration task: $failure"
  }

  $taskArn = [string]$result.tasks[0].taskArn
  Invoke-Aws -Arguments @("ecs", "wait", "tasks-stopped", "--cluster", $ClusterName, "--tasks", $taskArn, "--region", $Region) | Out-Null
  $task = Invoke-AwsJson -Arguments @("ecs", "describe-tasks", "--cluster", $ClusterName, "--tasks", $taskArn, "--region", $Region)
  $exitCode = $task.tasks[0].containers[0].exitCode
  if ($exitCode -ne 0) {
    $reason = [string]$task.tasks[0].stoppedReason
    throw "Migration task failed with exit code $($exitCode): $reason"
  }
  Write-Host "Migration completed successfully."
}

Require-Command -Name "aws"
Require-Command -Name "docker"
Require-Command -Name "git"

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
  throw "Configuration file not found: $ConfigPath"
}
if (-not (Test-Path -LiteralPath $SecretArnsPath -PathType Leaf)) {
  throw "Secret ARN file not found: $SecretArnsPath"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$secretMap = Get-Content -LiteralPath $SecretArnsPath -Raw | ConvertFrom-Json

foreach ($name in @(
  "awsRegion",
  "environment",
  "projectName",
  "clusterName",
  "backendRepository",
  "frontendRepository",
  "vpcId",
  "ecsSecurityGroupId",
  "executionRoleArn",
  "serviceConnectNamespaceArn",
  "frontendTargetGroupArn",
  "logsKmsKeyArn",
  "frontendUrl",
  "frontendOrigins",
  "backendOrigin"
)) {
  Assert-RealValue -Name $name -Value (Get-RequiredProperty -Object $config -Name $name)
}

if ($config.environment -notin @("staging", "production")) {
  throw "environment must be staging or production"
}
if ($config.backendOrigin -ne "http://api:8000") {
  throw "backendOrigin must be http://api:8000 for ECS Service Connect"
}
if ($config.environment -eq "production" -and ([uri]$config.frontendUrl).Scheme -ne "https") {
  throw "Production frontendUrl must use HTTPS"
}
if ($config.privateSubnetIds.Count -lt 2) {
  throw "privateSubnetIds must contain at least two subnets"
}
if ($config.frontendProxySubnetIds.Count -lt 2) {
  throw "frontendProxySubnetIds must contain at least two subnets"
}
if ((Get-DesiredCount -Config $config -Name "integration-dispatcher") -ne 1) {
  throw "integration-dispatcher must have desired count exactly 1"
}

$secretEntries = Get-SecretEntries -SecretMap $secretMap
$account = Invoke-AwsJson -Arguments @("sts", "get-caller-identity", "--region", $config.awsRegion)
$accountId = [string]$account.Account
$region = [string]$config.awsRegion
$registry = "{0}.dkr.ecr.{1}.amazonaws.com" -f $accountId, $region
$trustedProxyCidrs = @(Validate-AwsInputs -Config $config -SecretMap $secretMap -Region $region) -join ","
if ([string]::IsNullOrWhiteSpace($trustedProxyCidrs)) {
  throw "The frontend proxy subnets must expose trusted IPv4 CIDRs"
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
  $ImageTag = ((& git rev-parse --short=12 HEAD 2>$null) | Out-String).Trim()
}
if ([string]::IsNullOrWhiteSpace($ImageTag) -or $ImageTag -eq "HEAD") {
  throw "ImageTag is required when the repository is not at a Git revision"
}
if ($ImageTag -eq "latest") {
  throw "ImageTag=latest is not allowed; use an immutable Git revision"
}

$backendImage = "{0}/{1}:{2}" -f $registry, $config.backendRepository, $ImageTag
$frontendImage = "{0}/{1}:{2}" -f $registry, $config.frontendRepository, $ImageTag
$servicePrefix = "{0}-{1}" -f $config.projectName, $config.environment
$backendNetworkConfiguration = Get-NetworkConfiguration -Config $config -SubnetIds $config.privateSubnetIds
$frontendNetworkConfiguration = Get-NetworkConfiguration -Config $config -SubnetIds $config.frontendProxySubnetIds
$generatedDirectory = Join-Path $PSScriptRoot "generated"
$logRetentionDays = [int](Get-RequiredProperty -Object $config -Name "logRetentionDays")

$workerSpecs = @(
  [ordered]@{
    Name = "audit-worker"
    Command = @("python", "-m", "app.workers.audit_worker")
    FallbackCpu = 1024
    FallbackMemory = 2048
  },
  [ordered]@{
    Name = "audit-scheduler"
    Command = @("python", "-m", "app.workers.audit_scheduler")
    FallbackCpu = 256
    FallbackMemory = 512
    HealthCommand = "python -m app.workers.audit_scheduler --healthcheck"
  },
  [ordered]@{
    Name = "site-health-worker"
    Command = @("python", "-m", "app.workers.site_health_worker")
    FallbackCpu = 1024
    FallbackMemory = 2048
  },
  [ordered]@{
    Name = "brand-discovery-worker"
    Command = @("python", "-m", "app.workers.brand_discovery_worker")
    FallbackCpu = 512
    FallbackMemory = 1024
  },
  [ordered]@{
    Name = "content-worker"
    Command = @("python", "-m", "app.workers.content_worker")
    FallbackCpu = 512
    FallbackMemory = 1024
  },
  [ordered]@{
    Name = "analytics-worker"
    Command = @("python", "-m", "app.workers.analytics_worker")
    FallbackCpu = 512
    FallbackMemory = 1024
  },
  [ordered]@{
    Name = "integration-worker"
    Command = @("python", "-m", "app.workers.integration_worker")
    FallbackCpu = 512
    FallbackMemory = 1024
  },
  [ordered]@{
    Name = "integration-dispatcher"
    Command = @("python", "-m", "app.workers.integration_dispatcher")
    FallbackCpu = 256
    FallbackMemory = 512
  }
)

$backendEnvironment = @(
  [ordered]@{ name = "APP_ENV"; value = [string]$config.environment },
  [ordered]@{ name = "FRONTEND_URL"; value = [string]$config.frontendUrl },
  [ordered]@{ name = "FRONTEND_ORIGINS"; value = [string]$config.frontendOrigins },
  [ordered]@{ name = "TRUSTED_PROXY_CIDRS"; value = $trustedProxyCidrs },
  [ordered]@{ name = "DB_SSL_MODE"; value = "require" },
  [ordered]@{ name = "DB_POOL_SIZE"; value = [string](Get-RequiredProperty -Object $config -Name "dbPoolSize") },
  [ordered]@{ name = "DB_MAX_OVERFLOW"; value = [string](Get-RequiredProperty -Object $config -Name "dbMaxOverflow") },
  [ordered]@{ name = "AUDIT_WORKER_CONCURRENCY"; value = [string](Get-RequiredProperty -Object $config -Name "auditWorkerConcurrency") },
  [ordered]@{ name = "LOGFIRE_ENABLED"; value = "false" }
)

$optionalEnvironmentMap = [ordered]@{
  integrationGoogleClientId = "INTEGRATION_GOOGLE_CLIENT_ID"
  integrationMicrosoftClientId = "INTEGRATION_MICROSOFT_CLIENT_ID"
  billingRazorpayKeyId = "BILLING_RAZORPAY_KEY_ID"
  defaultAgentBaseUrl = "DEFAULT_AGENT_BASE_URL"
  defaultAgentModel = "DEFAULT_AGENT_MODEL"
  contentModel = "CONTENT_MODEL"
}
foreach ($propertyName in $optionalEnvironmentMap.Keys) {
  $property = $config.PSObject.Properties[$propertyName]
  if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
    $backendEnvironment += [ordered]@{
      name = $optionalEnvironmentMap[$propertyName]
      value = [string]$property.Value
    }
  }
}

$taskDefinitions = [ordered]@{}

$backendTaskSpecs = @(
  [ordered]@{
    Name = "api"
    ContainerName = "api"
    Image = $backendImage
    Command = @("uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000")
    Cpu = Get-TaskSize -Config $config -Name "api" -Property "cpu" -Fallback 512
    Memory = Get-TaskSize -Config $config -Name "api" -Property "memory" -Fallback 1024
    Port = 8000
    PortName = "api"
  },
  [ordered]@{
    Name = "migrate"
    ContainerName = "migrate"
    Image = $backendImage
    Command = @("alembic", "upgrade", "head")
    Cpu = Get-TaskSize -Config $config -Name "migrate" -Property "cpu" -Fallback 256
    Memory = Get-TaskSize -Config $config -Name "migrate" -Property "memory" -Fallback 512
    Port = 0
    PortName = ""
    HealthCommand = if ($spec.PSObject.Properties.Name -contains "HealthCommand") { $spec.HealthCommand } else { "exit 0" }
  }
)

foreach ($spec in $workerSpecs) {
  $backendTaskSpecs += [ordered]@{
    Name = $spec.Name
    ContainerName = $spec.Name
    Image = $backendImage
    Command = $spec.Command
    Cpu = Get-TaskSize -Config $config -Name $spec.Name -Property "cpu" -Fallback $spec.FallbackCpu
    Memory = Get-TaskSize -Config $config -Name $spec.Name -Property "memory" -Fallback $spec.FallbackMemory
    Port = 0
    PortName = ""
  }
}

foreach ($spec in $backendTaskSpecs) {
  $family = "$servicePrefix-$($spec.Name)"
  $logGroup = "/ecs/$servicePrefix/$($spec.Name)"
  $definition = New-BackendTaskDefinition -Family $family -ContainerName $spec.ContainerName -Image $spec.Image -Command $spec.Command -Cpu $spec.Cpu -Memory $spec.Memory -Environment $backendEnvironment -Secrets (Get-SecretEntriesForService -SecretMap $secretMap -ServiceName $spec.Name) -ExecutionRoleArn $config.executionRoleArn -LogGroup $logGroup -Region $region -ContainerPort $spec.Port -PortName $spec.PortName -WorkerHealthCommand $spec.HealthCommand
  $taskDefinitions[$spec.Name] = $definition
}

$frontendDefinition = New-FrontendTaskDefinition -Family "$servicePrefix-frontend" -Image $frontendImage -Cpu (Get-TaskSize -Config $config -Name "frontend" -Property "cpu" -Fallback 512) -Memory (Get-TaskSize -Config $config -Name "frontend" -Property "memory" -Fallback 1024) -BackendOrigin $config.backendOrigin -ExecutionRoleArn $config.executionRoleArn -LogGroup "/ecs/$servicePrefix/frontend" -Region $region
$taskDefinitions["frontend"] = $frontendDefinition

Write-Host "CiteLadder ECS deployment plan"
Write-Host "  AWS account: $accountId"
Write-Host "  Region:      $region"
Write-Host "  Environment: $($config.environment)"
Write-Host "  Cluster:     $($config.clusterName)"
Write-Host "  Image tag:   $ImageTag"
Write-Host "  Backend:     $backendImage"
Write-Host "  Frontend:    $frontendImage"
Write-Host "  Services:    $($taskDefinitions.Keys -join ', ')"

if (-not $Apply) {
  Write-Host ""
  Write-Host "Dry run only. Re-run with -Apply to build, push, register, migrate, and deploy."
  return
}

New-Item -ItemType Directory -Path $generatedDirectory -Force | Out-Null
Ensure-EcrRepository -RepositoryName $config.backendRepository -Region $region
Ensure-EcrRepository -RepositoryName $config.frontendRepository -Region $region

$loginPassword = Invoke-Aws -Arguments @("ecr", "get-login-password", "--region", $region)
$loginPassword | docker login --username AWS --password-stdin $registry
if ($LASTEXITCODE -ne 0) {
  throw "Docker login to ECR failed"
}

$backendLocal = "citeladder-backend:$ImageTag"
$frontendLocal = "citeladder-frontend:$ImageTag"

Invoke-Native -Command "docker" -Arguments @("build", "--file", "Dockerfile", "--tag", $backendLocal, "--label", "org.opencontainers.image.revision=$ImageTag", ".") | Out-Null
Invoke-Native -Command "docker" -Arguments @("build", "--file", "infra/aws/frontend.Dockerfile", "--build-arg", "BACKEND_ORIGIN=$($config.backendOrigin)", "--tag", $frontendLocal, "--label", "org.opencontainers.image.revision=$ImageTag", ".") | Out-Null

Invoke-Native -Command "docker" -Arguments @("tag", $backendLocal, $backendImage) | Out-Null
Invoke-Native -Command "docker" -Arguments @("tag", $frontendLocal, $frontendImage) | Out-Null
Invoke-Native -Command "docker" -Arguments @("push", $backendImage) | Out-Null
Invoke-Native -Command "docker" -Arguments @("push", $frontendImage) | Out-Null

Ensure-Cluster -ClusterName $config.clusterName -Region $region

$registered = [ordered]@{}
foreach ($name in $taskDefinitions.Keys) {
  $logGroup = "/ecs/$servicePrefix/$name"
  Ensure-LogGroup -Name $logGroup -RetentionDays $logRetentionDays -Region $region -KmsKeyArn $config.logsKmsKeyArn
  $path = Join-Path $generatedDirectory "$name.json"
  $registered[$name] = Register-TaskDefinition -Definition $taskDefinitions[$name] -OutputPath $path -Region $region
}

$serviceConnectApi = @{
  enabled = $true
  namespace = [string]$config.serviceConnectNamespaceArn
  services = @(
    @{
      portName = "api"
      discoveryName = "api"
      clientAliases = @(
        @{
          port = 8000
          dnsName = "api"
        }
      )
    }
  )
} | ConvertTo-Json -Depth 10 -Compress

$serviceConnectClient = @{
  enabled = $true
  namespace = [string]$config.serviceConnectNamespaceArn
} | ConvertTo-Json -Depth 10 -Compress

Run-Migration -ClusterName $config.clusterName -TaskDefinitionArn $registered["migrate"] -NetworkConfiguration $backendNetworkConfiguration -Region $region

$apiService = "$servicePrefix-api"
$frontendService = "$servicePrefix-frontend"

Ensure-Service -ClusterName $config.clusterName -ServiceName $apiService -TaskDefinitionArn $registered["api"] -DesiredCount (Get-DesiredCount -Config $config -Name "api") -Region $region -NetworkConfiguration $backendNetworkConfiguration -ServiceConnectConfiguration $serviceConnectApi

Ensure-Service -ClusterName $config.clusterName -ServiceName $frontendService -TaskDefinitionArn $registered["frontend"] -DesiredCount (Get-DesiredCount -Config $config -Name "frontend") -Region $region -NetworkConfiguration $frontendNetworkConfiguration -ServiceConnectConfiguration $serviceConnectClient -TargetGroupArn $config.frontendTargetGroupArn -ContainerName "frontend" -ContainerPort 3000

foreach ($spec in $workerSpecs) {
  $serviceName = "$servicePrefix-$($spec.Name)"
  Ensure-Service -ClusterName $config.clusterName -ServiceName $serviceName -TaskDefinitionArn $registered[$spec.Name] -DesiredCount (Get-DesiredCount -Config $config -Name $spec.Name) -Region $region -NetworkConfiguration $backendNetworkConfiguration -ServiceConnectConfiguration $serviceConnectClient
}

Write-Host ""
Write-Host "Deployment completed successfully."
Write-Host "Frontend service: $frontendService"
Write-Host "API service:      $apiService"
