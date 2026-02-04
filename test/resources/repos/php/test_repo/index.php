<?php

require_once 'helper.php';

function greet(string $name): string {
    return "Hello, " . $name . "!";
}

$userName = "PHP User";
$greeting = greet($userName);

echo $greeting;

helperFunction();

function useHelperFunction() {
    helperFunction();
}

?> 