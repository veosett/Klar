import java.util.*;

public class Main {
    record Person(String name, int age) {}

    public static void main(String[] args) {
        List<Person> people = new ArrayList<>(List.of(new Person("cat", 3), new Person("ann", 1), new Person("bob", 2)));
        Collections.sort(people); // BUG: Person has no order; meant sort by age
        System.out.println(String.join(",", people.stream().map(Person::name).toList()));
    }
}
