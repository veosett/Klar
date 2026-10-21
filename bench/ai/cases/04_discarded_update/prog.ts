const userName = "  ann  ";
userName.trim(); // BUG: the trimmed copy is thrown away
console.log(`[${userName}]`);
