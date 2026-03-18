#include <stdio.h>
int main () {
int a, number1, number2, sum;
printf("Enter First Number: ");
scanf("%d", &number1);
printf("Enter Second Number: ");
scanf("%d", &number2);
sum = number1 + number2;
printf("In Addition of %d and %d is %d\n",
number1, number2, sum);
return 0;
}
